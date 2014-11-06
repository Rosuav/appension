"""
Based off of `capsule`, by Tristan Jehan and Jason Sundram.
Heavily modified by Peter Sobot for integration with forever.fm.
Again by Mike iLL and Rosuav for Infinite Glitch
"""
import os
import gc
import apikeys
import logging
import urllib2
import traceback
import threading
import multiprocessing

from lame import Lame
from timer import Timer
import database

from audio import AudioData

from capsule_support import order_tracks, resample_features, \
                            timbre_whiten, initialize, make_transition, terminate, \
                            FADE_OUT, is_valid, LOUDNESS_THRESH

log = logging.getLogger(__name__)

import sys
test = 'test' in sys.argv

##########################################
## Code lifted from psobot's pyechonest ##
##########################################
import hashlib
import time

from pyechonest.util import EchoNestAPIError
import pyechonest.util
import weakref
from echonest.support.ffmpeg import ffmpeg, FFMPEGStreamHandler
class AudioStream(object):
    """
    Very much like an AudioData, but vastly more memory efficient.
    However, AudioStream only supports sequential access - i.e.: one, un-seekable
    stream of PCM data directly being streamed from FFMPEG.
    """

    def __init__(self, fobj):
        self.sampleRate = 44100
        self.numChannels = 2
        self.fobj = fobj
        self.stream = FFMPEGStreamHandler(self.fobj, self.numChannels, self.sampleRate)
        self.index = 0

    def __getitem__(self, index):
        """
        Fetches a frame or slice. Returns an individual frame (if the index
        is a time offset float or an integer sample number) or a slice if
        the index is an `AudioQuantum` (or quacks like one). If the slice is
        "in the past" (i.e.: has been read already, or the current cursor is
        past the requested slice) then this will throw an exception.
        """
        if isinstance(index, float):
            index = int(index * self.sampleRate)
        elif hasattr(index, "start") and hasattr(index, "duration"):
            index =  slice(float(index.start), index.start + index.duration)

        if isinstance(index, slice):
            if (hasattr(index.start, "start") and
                 hasattr(index.stop, "duration") and
                 hasattr(index.stop, "start")):
                index = slice(index.start.start, index.stop.start + index.stop.duration)

        if isinstance(index, slice):
            return self.getslice(index)
        else:
            return self.getsample(index)

    def getslice(self, index):
        "Help `__getitem__` return a new AudioData for a given slice"
        if isinstance(index.start, float):
            index = slice(int(index.start * self.sampleRate),
                            int(index.stop * self.sampleRate), index.step)
        if index.start < self.index:
            self.stream.finish()
            self.stream = FFMPEGStreamHandler(self.fobj, self.numChannels, self.sampleRate)
            self.index = 0
        if index.start > self.index:
            self.stream.feed(index.start - self.index)
        self.index = index.stop

        return AudioData(None, self.stream.read(index.stop - index.start),
                            sampleRate=self.sampleRate,
                            numChannels=self.numChannels, defer=False)

    def getsample(self, index):
        #   TODO: Finish this properly
        raise NotImplementedError()
        if isinstance(index, float):
            index = int(index * self.sampleRate)
        if index >= self.index:
            self.stream.feed(index.start - self.index)
            self.index += index
        else:
            raise ValueError("Cannot seek backwards in AudioStream")

    def render(self):
        return self.stream.read()

    def finish(self):
        self.stream.finish()

    def __del__(self):
        if hasattr(self, "stream"):
            self.stream.finish()


class LocalAudioStream(AudioStream):
    """
    Like a non-seekable LocalAudioFile with vastly better memory usage
    and performance. Takes a file-like object (and its kind, assumed
    to be MP3) and supports slicing and rendering. Attempting to read
    from a part of the input file that has already been read will throw
    an exception.
    """
    def __init__(self, initializer, kind="mp3"):
        AudioStream.__init__(self, initializer)

        start = time.time()
        if hasattr(initializer, 'seek'):
            fobj = initializer
            fobj.seek(0)
        else:
            fobj = open(initializer, 'r')
        #   This looks like a lot of work, but is much more lighter
        #   on memory than reading the entire file in.
        md5 = hashlib.md5()
        while True:
            data = fobj.read(2 ^ 16)
            if not data:
                break
            md5.update(data)
        if not hasattr(initializer, 'seek'):
            fobj.close()
        track_md5 = md5.hexdigest()

        logging.getLogger(__name__).info("Fetching analysis...")
        try:
            tempanalysis = AudioAnalysis(str(track_md5))
        except EchoNestAPIError:
            tempanalysis = AudioAnalysis(initializer, kind)

        logging.getLogger(__name__).info("Fetched analysis in %ss",
                                         (time.time() - start))
        self.analysis = tempanalysis
        self.analysis.source = weakref.ref(self)

        class data(object):
            """
            Massive hack - certain operations are intrusive and check
            `.data.ndim`, so in this case, we fake it.
            """
            ndim = self.numChannels

        self.data = data
##############################################
## End code lifted from psobot's pyechonest ##
##############################################


def metadata_of(a):
    if hasattr(a, '_metadata'):
        return a._metadata.obj
    if hasattr(a, 'track'):
        return metadata_of(a.track)
    if hasattr(a, 't1') and hasattr(a, 't2'):
        return (metadata_of(a.t1), metadata_of(a.t2))
    raise ValueError("No metadata found!")


def generate_metadata(a):
    d = {
        'action': a.__class__.__name__.split(".")[-1],
        'duration': a.duration,
        'samples': a.samples
    }
    m = metadata_of(a)
    if isinstance(m, tuple):
        m1, m2 = m
        d['tracks'] = [{
            "metadata": m1,
            "start": a.s1,
            "end": a.e1
        }, {
            "metadata": m2,
            "start": a.s2,
            "end": a.e2
        }]
    else:
        d['tracks'] = [{
            "metadata": m,
            "start": a.start,
            "end": a.start + a.duration
        }]
    return d


class Mixer(multiprocessing.Process):
    def __init__(self, iqueue, oqueues, infoqueue,
                 settings=({},), initial=None,
                 max_play_time=300, transition_time=30 if not test else 5,
                 samplerate=44100):
        self.iqueue = iqueue
        self.infoqueue = infoqueue

        self.encoders = []
        if len(oqueues) != len(settings):
            raise ValueError("Differing number of output queues and settings!")

        self.oqueues = oqueues
        self.settings = settings

        self.__track_lock = threading.Lock()
        self.__tracks = []

        self.max_play_time = max_play_time
        self.transition_time = transition_time
        self.samplerate = 44100
        self.__stop = False

        if isinstance(initial, list):
            self.add_tracks(initial)
        elif isinstance(initial, AudioData):
            self.add_track(initial)

        multiprocessing.Process.__init__(self)

    @property
    def tracks(self):
        self.__track_lock.acquire()
        tracks = self.__tracks
        self.__track_lock.release()
        return tracks

    @tracks.setter
    def tracks(self, new_val):
        self.__track_lock.acquire()
        self.__tracks = new_val
        self.__track_lock.release()

    @property
    def current_track(self):
        return self.tracks[0]

    def get_stream(self, x):
	print(os.getcwd)
	print(x.filename)
        for fname in (x.filename, "audio/"+x.filename):
            if os.path.isfile(fname):
                return fname
        # TODO: Fetch the contents from the database and save to fname
        raise NotImplementedError

    def analyze(self, x):
        if isinstance(x, list):
            return [self.analyze(y) for y in x]
        if isinstance(x, AudioData):
            return self.process(x)
        if isinstance(x, tuple):
            return self.analyze(*x)

        log.info("Grabbing stream [%r]...", x.id)
        laf = LocalAudioStream(self.get_stream(x))
        setattr(laf, "_metadata", x)
        return self.process(laf)

    def add_track(self, track):
        self.tracks.append(self.analyze(track))

    def add_tracks(self, tracks):
        self.tracks += order_tracks(self.analyze(tracks))

    def process(self, track):
        if not hasattr(track.analysis.pyechonest_track, "title"):
            setattr(track.analysis.pyechonest_track, "title", track._metadata.title)
        log.info("Resampling features [%r]...", track._metadata.id)
        track.resampled = resample_features(track, rate='beats')
        track.resampled['matrix'] = timbre_whiten(track.resampled['matrix'])

        if not is_valid(track, self.transition_time):
            raise ValueError("Track too short!")

        track.gain = self.__db_2_volume(track.analysis.loudness)
        log.info("Done processing [%r].", track._metadata.id)
        return track

    def __db_2_volume(self, loudness):
        return (1.0 - LOUDNESS_THRESH * (LOUDNESS_THRESH - loudness) / 100.0)

    def loop(self):
        while len(self.tracks) < 2:
            log.info("Waiting for a new track.")
            track = self.iqueue.get()
            try:
                self.add_track(track)  # TODO: Extend to allow multiple tracks.
                log.info("Got a new track.")
            except Exception:
                log.error("Exception while trying to add new track:\n%s",
                          traceback.format_exc())

        # Initial transition. Should contain 2 instructions: fadein, and playback.
	inter = self.tracks[0].analysis.duration
        yield initialize(self.tracks[0], inter, self.transition_time, 10)

        while not self.__stop:
            while len(self.tracks) > 1:
                stay_time = max(self.tracks[0].analysis.duration,
                                self.tracks[1].analysis.duration)
                tra = make_transition(self.tracks[0],
                                      self.tracks[1],
                                      stay_time,
                                      self.transition_time)
                del self.tracks[0].analysis
                gc.collect()
                yield tra
                self.tracks[0].finish()
                del self.tracks[0]
                gc.collect()
            log.info("Waiting for a new track.")
            try:
                self.add_track(self.iqueue.get())  # TODO: Allow multiple tracks.
                log.info("Got a new track.")
            except ValueError:
                log.warning("Track too short! Trying another.")
            except Exception:
                log.error("Exception while trying to add new track:\n%s",
                          traceback.format_exc())

        log.error("Stopping!")
        # Last chunk. Should contain 1 instruction: fadeout.
        yield terminate(self.tracks[-1], FADE_OUT)

    def run(self):
        for oqueue, settings in zip(self.oqueues, self.settings):
            e = Lame(oqueue=oqueue, **settings)
            self.encoders.append(e)
            e.start()

        try:
            self.ctime = None
            for i, actions in enumerate(self.loop()):
                log.info("Rendering audio data for %d actions.", len(actions))
                for a in actions:
                    try:
                        with Timer() as t:
                            #   TODO: Move the "multiple encoding" support into
                            #   LAME itself - it should be able to multiplex the
                            #   streams itself.
                            self.encoders[0].add_pcm(a)
                            self.infoqueue.put(generate_metadata(a))
                        log.info("Rendered in %fs!", t.ms)
                    except Exception:
                        log.error("Could not render %s. Skipping.\n%s", a,
                                  traceback.format_exc())
                gc.collect()
        except Exception:
            log.error("Something failed in mixer.run:\n%s",
                      traceback.format_exc())
            self.stop()
            return

    def stop(self):
        self.__stop = True

    @property
    def stopped(self):
        return self.__stop
