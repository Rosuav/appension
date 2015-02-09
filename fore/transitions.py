#!/usr/bin/env python
# encoding: utf=8

"""
capsule_support.py

Created by Tristan Jehan and Jason Sundram.
"""
import logging
from action import Crossfade as cf
from action import Playback as pb

log = logging.getLogger(__name__)

LOUDNESS_THRESH = -8

def last_viable(track):
	for seg in reversed(track.analysis.segments):
		if seg.loudness_max > -60:
			#time of last audible piece of track
			return seg.start + seg.duration
			
def first_viable(track):
	for seg in track.analysis.segments:
		if seg.loudness_max > -60:
			#time of first audible segment of track
			return seg.start
			

					
def end_trans(track, beats_to_mix = 0):
	"""
	Return tuples with times to be sent to Playback and Crossmix objects
	"""
	end_viable = last_viable(track)
	try:
		avg_duration = sum([b.duration for b in track.analysis.tatums[-16:]]) / 16
	except IndexError:
		avg_duration = sum([b.duration for b in track.analysis.segments[-8:]]) / 8
	#How much of the track are we returning - adjust for beats to mix?
	half_way_point = len(track.analysis.segments) / 2
	start = track.analysis.segments[half_way_point].start
	if beats_to_mix > 0:
		#if we're crossfading, playback ends at first beat of crossfade
		playback_end = end_viable - (avg_duration * beats_to_mix)
		final =  int(beats_to_mix) #count tatums from end of tatum list

	else:
		#if we're not crossfading playback to end, final beat being last tatum
		playback_end = end_viable
		final = 1
		
	try:
		track.analysis.tatums[-1]
	except IndexError:
		# if no tatums play through end of track
		final_segments = {"subsequent_beat": track.analysis.segments[-final].start}
		final_segments["playback_start"] = start
		final_segments["playback_duration"] = playback_end - final_segments["playback_start"]
		final_segments["mix_start"] = final_segments['subsequent_beat']
		final_segments["mix_duration"] = end_viable - final_segments['subsequent_beat']
		final_segments["avg_duration"] = avg_duration
		return final_segments

	final_segments = {"subsequent_beat": track.analysis.tatums[-final].start}
	while final_segments['subsequent_beat'] < playback_end:
		#get first "beat" following end of playback
		final_segments['subsequent_beat'] += avg_duration

	final_segments["playback_start"] = start
	final_segments["playback_duration"] = playback_end - final_segments["playback_start"]
	final_segments["mix_start"] = final_segments['subsequent_beat']
	final_segments["mix_duration"] = end_viable - final_segments['subsequent_beat']
	final_segments["avg_duration"] = avg_duration

	return final_segments
	
def db_2_volume(loudness):
		return (1.0 - LOUDNESS_THRESH * (LOUDNESS_THRESH - loudness) / 100.0)
		
def initialize(track1, track2):
    log.info("st now we got track1: %s and track2: %s", track1._metadata.track_details['artist'], track2._metadata.track_details['artist'])
    for track in [track1, track2]:
        loudness = track.analysis.loudness
        track.gain = db_2_volume(loudness)
		
    xfade = float(track1._metadata.track_details['xfade'])
    itrim = float(track2._metadata.track_details['itrim'])
    otrim = float(track1._metadata.track_details['otrim'])

    
    if xfade == 0:
        times = end_trans(track1)
        if times["playback_duration"] - otrim < 0:
            raise Exception("You can't trim off more than 100%.")
        pb1 = pb(track1, 0, times["playback_duration"] - otrim)
        pb2 = pb(track2, first_viable(track2), pb1.duration + 10)
        return [pb1, pb2]
    else:
        times = end_trans(track1, beats_to_mix=xfade)
        log.info("times mix_duration is %r", times["mix_duration"])
        '''We would start at zero, but make it first audible segment'''
        t2start = first_viable(track2)
        '''offset between start and first theoretical beat.'''
        t2offset = lead_in(track2)
        pb1 = pb(track1, 0, times["playback_duration"] - t2offset)
        pb2 = cf((track1, track2), (times["playback_start"] + times["playback_duration"] - t2offset, t2start), times["mix_duration"])
        start_point['cursor'] = t2start + times["mix_duration"]
        log.info('''
        track1 start: %r, track2 start: %r, duration: %r
        ''',times["playback_start"] + times["playback_duration"] - t2offset, t2start, track1._metadata.track_details['length'])
        log.info("New cf item: %r", pb2.duration)
        log.info("Which looks like: %r", pb2.t2.start)
        return [pb1, pb2]


def terminate(track):
	""" Deal with last track"""
	log.info(dir(track))
	pb1 = pb(track, 0, 100)
	return [pb1]
	
start_point = {"cursor": 0}
	
def managed_transition(track1, track2):
    log.info("now we got track1: %s and track2: %s", track1._metadata.track_details['artist'], track2._metadata.track_details['artist'])
    for track in [track1, track2]:
        loudness = track.analysis.loudness
        track.gain = db_2_volume(loudness)

    xfade = float(track1._metadata.track_details['xfade'])
    itrim = float(track2._metadata.track_details['itrim'])
    otrim = float(track1._metadata.track_details['otrim'])

    if xfade == 0:
        log.info("xfade = ", xfade)
        times = end_trans(track1)
        if times["playback_duration"] - otrim < 0:
            raise Exception("You can't trim off more than 100%.")
        pb1 = pb(track1, start_point['cursor'], track1._metadata.track_details['length'])
        pb2 = pb(track2, first_viable(track2) + itrim, track1._metadata.track_details['length'] - track2._metadata.track_details['otrim'])
        start_point['cursor'] = t2start + times["mix_duration"]
        return [pb1, pb2]
    else:
        times = end_trans(track1, beats_to_mix=xfade)
        log.info("times mix_duration is %r", times["mix_duration"])
        '''We would start at zero, but make it first audible segment'''
        t2start = first_viable(track2)
        '''offset between start and first theoretical beat.'''
        t2offset = lead_in(track2)
        pb1 = pb(track1, start_point['cursor'], times["playback_duration"] - t2offset)
        pb2 = cf((track1, track2), (times["playback_start"] + times["playback_duration"] - t2offset, t2start), times["mix_duration"])
        start_point['cursor'] = t2start + times["mix_duration"]
        log.info('''
        track1 start: %r, track2 start: %r, duration: %r
        ''',times["playback_start"] + times["playback_duration"] - t2offset, t2start, track1._metadata.track_details['length'])
        log.info("New cf item: %r", pb2.duration)
        log.info("Which looks like: %r", pb2.t2.start)
        return [pb1, pb2]

def lead_in(track):
	"""
	Return the time between start of track and first beat.
	"""
	avg_duration = sum([b.duration for b in track.analysis.beats[:8]]) / 8
	try:
		earliest_beat = track.analysis.beats[0].start
	except IndexError:
		earliest_beat = track.analysis.segments[0].start
	while earliest_beat > 0:
		earliest_beat -= avg_duration
	offset = earliest_beat
	return offset