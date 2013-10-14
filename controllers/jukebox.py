'''
@author: Dimitrios Kanellopoulos
@contact: jimmykane9@gmail.com
'''
import os
import re
import logging
import datetime
import json
import random
from models.person import *
from models.tracks import *
from models.jukebox import *
from controllers.jsonhandler import *

from google.appengine.api import taskqueue

import webapp2

''' All responses must be JSON encoded '''

class GetJukeBoxesHandler(webapp2.RequestHandler, JSONHandler):

	def post(self):

		# First lets try to get the data and then logic
		try:
			data = json.loads(self.request.body)
			jukebox_ids = data['jukebox_ids']
			filters = data['filters']
		except Exception as e:
			logging.error('Unconvertable request' + repr(e))
			response = {'status':self.get_status(status_code=400, msg=repr(e))}
			self.response.out.write(json.dumps(response))
			return
		if filters:
			# Needs implementation here
			pass
		if jukebox_ids:
			jukeboxes = ndb.get_multi([ndb.Key(Jukebox, id) for id in jukebox_ids])
		else:
			jukeboxes = Jukebox.query().order(Jukebox.creation_date).fetch(100)
		if not jukeboxes:
			response = {'status':self.get_status(status_code=404)}
			self.response.out.write(json.dumps(response))
			return

		jukeboxes = Jukebox.jukeboxes_and_queued_tracks_to_dict(jukeboxes)
		response = {'data': jukeboxes}
		response.update({'status': self.get_status()})
		logging.info(response)
		self.response.out.write(json.dumps(response))
		return


class GetJukeBoxQueuedTracksHandler(webapp2.RequestHandler, JSONHandler):

	def post(self):

		# First lets try to get the data and then logic
		try:
			data = json.loads(self.request.body)
			jukebox_id = data['jukebox_id']
			filters = data['filters']
		except Exception as e:
			logging.error('Unconvertable request' + repr(e))
			response = {'status':self.get_status(status_code=400, msg=repr(e))}
			self.response.out.write(json.dumps(response))
			return

		archived = False
		if filters:
			if 'archived' in filters:
				archived = True

		if not jukebox_id:
			response = {'status':self.get_status(status_code=400, msg=repr(e))}
			self.response.out.write(json.dumps(response))

		jukebox_key = ndb.Key(Jukebox, jukebox_id)

		# only queued tracks
		queued_tracks = QueuedTrack.query(ancestor=jukebox_key).filter(QueuedTrack.archived==archived).order(-QueuedTrack.edit_date).fetch(1000)
		queued_tracks_list = []
		for queued_track in queued_tracks:
			queued_track_id = queued_track.key.id()
			queued_track = queued_track.to_dict(exclude=['queued_by_person_key','creation_date', 'edit_date'])
			queued_track.update({'id': queued_track_id})
			queued_tracks_list.append(queued_track)


		response = {'data': queued_tracks_list}
		response.update({'status': self.get_status()})
		self.response.out.write(json.dumps(response))
		return


class GetPlayingTrackHandler(webapp2.RequestHandler, JSONHandler):

	def post(self):

		# First lets try to get the data and then logic
		try:
			data = json.loads(self.request.body)
			#logging.info(self.request.body)
			jukebox_id = data
			# inside the try due to wrong posts etc of id
			jukebox = ndb.Key(Jukebox, jukebox_id).get()
		except Exception as e:
			logging.error('Unconvertable request' + repr(e))
			response = {'status':self.get_status(status_code=400, msg=repr(e))}
			self.response.out.write(json.dumps(response))
			return

		#logging.info(jukebox)
		if not jukebox:
			response = {'status':self.get_status(status_code=404, msg='Sorry but no jukebox')}
			self.response.out.write(json.dumps(response))
			return
		if not jukebox.player.on:
			response = {'status':self.get_status(status_code=403, msg='Jukebox is off')}
			self.response.out.write(json.dumps(response))
			return

		player = jukebox.player
		#logging.info(player)

		track_playing = jukebox.track_playing

		if not track_playing:
			response = {'status':self.get_status(status_code=403, msg='Sorry no track is playing atm..')}
			self.response.out.write(json.dumps(response))
			return

		elapsed = datetime.datetime.now() - player.track_queued_on
		start_seconds = elapsed.total_seconds()

		# elapsed greater than total seconds should reset
		if start_seconds > track_playing.duration:
			logging.info('Current song has ended')
			response = {'status':self.get_status(status_code=403, msg='Last song ended? Or jukebox is jammed?')}
			self.response.out.write(json.dumps(response))
			return

		track_playing_id = track_playing.key.id()
		person = track_playing.queued_by_person_key.get()
		track_playing = track_playing.to_dict(exclude=['queued_by_person_key','track_key','creation_date', 'edit_date'])
		track_playing.update({'id': track_playing_id})
		track_playing.update({'person_nick_name': person.info.nick_name})
		track_playing.update({'start_seconds': start_seconds})

		response = {'data': track_playing}
		response.update({'status': self.get_status()})
		#logging.info(response)
		self.response.out.write(json.dumps(response))


'''
	This handler will fire next track tasks with an eta.
'''
#shoulb be moved again to seperate controller i think.
#no need to be here.
class StartPlayingHandler(webapp2.RequestHandler, JSONHandler):

	def post(self):

		person = Person.get_current()
		if not person: # its normal now
			response = {'status':self.get_status(status_code=404)}
			self.response.out.write(json.dumps(response))
			return
		# First lets try to get the data and then logic
		try:
			data = json.loads(self.request.body)
			jukebox_id = data['jukebox_id']
			queued_track_id = data['queued_track_id']
			seek = data['seek']
		except Exception as e:
			logging.error('Unconvertable request' + repr(e))
			response = {'status':self.get_status(status_code=400, msg=repr(e))}
			self.response.out.write(json.dumps(response))
			return
		# is there a jukebox ?
		jukebox = ndb.Key(Jukebox, jukebox_id).get()
		if not jukebox:
			response = {'status':self.get_status(status_code=404)}
			self.response.out.write(json.dumps(response))
			return
		if jukebox.owner_key != person.key:
			response = {'status':self.get_status(status_code=404)}
			self.response.out.write(json.dumps(response))
			return
		queued_track = ndb.Key(
			Jukebox, jukebox_id,
			QueuedTrack, queued_track_id
		).get()

		if not queued_track:
			logging.info('Brrrrr')
			return

		if not seek: #should also check if the seek is bigger than dur
			seek = 0

		#transaction here please!!!!!!!!!
		player = jukebox.player

		player.on = True

		# if it's set the start time please add the elaspsed
		player.track_queued_on = datetime.datetime.now() - datetime.timedelta(0, seek)
		player.track_duration = queued_track.duration
		player.track_key = queued_track.key # it is the same with the track
		player.put()
		#logging.info(player)
		#return

		taskqueue.add(
			queue_name = "playercommands",
			url="/playercommands/next/",
			method='POST',
			eta=player.track_queued_on + datetime.timedelta(0, player.track_duration),
			target=(None if self.is_dev_server() else 'playercommands'),
			params= {
				'jukebox_id': jukebox.key.id(),
				'track_key_id': player.track_key.id(),
				'track_queued_on': player.track_queued_on.isoformat()
				# date will be in iso format 2013-10-09 07:54:56.871812
			},
			headers={"X-AppEngine-FailFast":"true"} # for now
		)

		queued_track.archived = True
		queued_track.put()
		logging.info('Added and player has started')
		#logging.info('Track title: ' + str(str(queued_track.title)))
		response = {'status': self.get_status()}
		self.response.out.write(json.dumps(response))
		return


'''
	This handler will fire next track tasks with an eta.
'''
#shoulb be moved again to seperate controller i think.
#no need to be here.
class StopPlayingHandler(webapp2.RequestHandler, JSONHandler):

	def post(self):

		person = Person.get_current()
		if not person: # its normal now
			response = {'status':self.get_status(status_code=404)}
			self.response.out.write(json.dumps(response))
			return
		# First lets try to get the data and then logic
		try:
			data = json.loads(self.request.body)
			jukebox_id = data['jukebox_id']
		except Exception as e:
			logging.error('Unconvertable request' + repr(e))
			response = {'status':self.get_status(status_code=400, msg=repr(e))}
			self.response.out.write(json.dumps(response))
			return
		# is there a jukebox ?
		jukebox = ndb.Key(Jukebox, jukebox_id).get()
		if not jukebox:
			response = {'status':self.get_status(status_code=404)}
			self.response.out.write(json.dumps(response))
			return
		if jukebox.owner_key != person.key:
			response = {'status':self.get_status(status_code=404)}
			self.response.out.write(json.dumps(response))
			return
		#transaction here please!!!!!!!!!
		player = jukebox.player

		player.on = False

		player.put()
		#logging.info(player.track_key)
		#return
		logging.info('Player stopped')
		response = {'status': self.get_status()}
		self.response.out.write(json.dumps(response))
		return



class SaveJukeBoxeHandler(webapp2.RequestHandler, JSONHandler):

	def post(self):

		person = Person.get_current()
		if not person:
			logging.warning('Unauthorized')
			response = {'status': self.get_status(status_code=401)}
			self.response.out.write(json.dumps(response))
			return
		try:
			jukebox_to_save = json.loads(self.request.body)
			#logging.info(jukebox_to_save)
			if not jukebox_to_save:
				response = {'status':self.get_status(status_code=404)}
				self.response.out.write(json.dumps(response))
				return
		except Exception as e:
			logging.exception('Unconvertable request' + repr(e))
			response = {'status': self.get_status(status_code=400, msg=repr(e))}
			self.response.out.write(json.dumps(response))
			return
		#logging.info(jukebox_to_save)
		jukebox = Jukebox.entity_from_dict(None, jukebox_to_save)
		#logging.info(jukebox_to_save.title)
		#logging.info(jukebox)
		#this before put
		# should also get before to be sure it exists and not
		# sure.

		jukebox.put()
		if not jukebox:
			response = {'status': self.get_status(status_code=404)}
			self.response.out.write(json.dumps(response))
			return
		jukeboxes = Jukebox.jukeboxes_and_queued_tracks_to_dict([jukebox])
		response = {'data': jukeboxes[0]}
		response.update({'status': self.get_status()})
		#logging.info(response)
		self.response.out.write(json.dumps(response))
		return


	#@ndb.transactional(retries=6)
	#def _save_slides_transactional(self, slides_to_save):
		#person = Person.get_current()
		#if not person:
			#return False
		#slides = []
		#for slide_to_save in slides_to_save:
			#slide = Slide.entity_from_dict(person.key, slide_to_save)
			#if not slide: # if cannot construct the slide something is wrong
				#return False
			#slide.put()
			#slides.append(slide)
			#for box_to_save in slide_to_save['boxes']:
				#box = Box.entity_from_dict(slide.key, box_to_save)
				#if not box:
					#return False
				#box.put()
				## There is no need to get it again because the convert gets them
		#return slides