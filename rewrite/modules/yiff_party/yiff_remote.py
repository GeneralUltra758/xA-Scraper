
import os
import os.path
import traceback
import re
import logging
import datetime
import urllib.request
import urllib.parse
import time
import json
import copy
import uuid
import pprint

import bs4
import dateparser

import rewrite.modules.scraper_base
import rewrite.modules.rpc_base

import flags

from settings import settings

class RpcTimeoutError(RuntimeError):
	pass
class RpcExceptionError(RuntimeError):
	pass


class RemoteExecClass(object):
	# # ---------------------------------------------------------------------------------------------------------------------------------------------------------
	# Runtime management
	# # ---------------------------------------------------------------------------------------------------------------------------------------------------------

	url_base = 'https://yiff.party/'

	def __init__(self, wg=None):
		self.logname = "Main.RemoteExec.Tester"
		self.out_buffer = []
		self.local_logger = logging.getLogger(self.logname)
		self.wg = wg

		self.__install_logproxy()

		self.log.info("RemoteExecClass Instantiated")

	def __install_logproxy(self):
		class LogProxy():
			def __init__(self, parent_logger, log_prefix):
				self.parent_logger = parent_logger
				self.log_prefix    = log_prefix
			def debug(self, msg, *args):
				self.parent_logger._debug   (" [{}] -> ".format(self.log_prefix) + msg, *args)
			def info(self, msg, *args):
				self.parent_logger._info    (" [{}] -> ".format(self.log_prefix) + msg, *args)
			def error(self, msg, *args):
				self.parent_logger._error   (" [{}] -> ".format(self.log_prefix) + msg, *args)
			def critical(self, msg, *args):
				self.parent_logger._critical(" [{}] -> ".format(self.log_prefix) + msg, *args)
			def warning(self, msg, *args):
				self.parent_logger._warning (" [{}] -> ".format(self.log_prefix) + msg, *args)
			def warn(self, msg, *args):
				self.parent_logger._warning (" [{}] -> ".format(self.log_prefix) + msg, *args)

		self.wg.log = LogProxy(self, "WebGet")
		self.log    = LogProxy(self, "MainRPCAgent")


	def _debug(self, msg, *args):
		tmp = self.logname + " [DEBUG] ->" + msg % args
		self.local_logger.debug(tmp)
		self.out_buffer.append(tmp)
	def _info(self, msg, *args):
		tmp = self.logname + " [INFO] ->" + msg % args
		self.local_logger.info(tmp)
		self.out_buffer.append(tmp)
	def _error(self, msg, *args):
		tmp = self.logname + " [ERROR] ->" + msg % args
		self.local_logger.error(tmp)
		self.out_buffer.append(tmp)
	def _critical(self, msg, *args):
		tmp = self.logname + " [CRITICAL] ->" + msg % args
		self.local_logger.critical(tmp)
		self.out_buffer.append(tmp)
	def _warning(self, msg, *args):
		tmp = self.logname + " [WARNING] ->" + msg % args
		self.local_logger.warning(tmp)
		self.out_buffer.append(tmp)


	def go(self, *args, **kwargs):
		try:
			ret = self._go(*args, **kwargs)
			return (self.out_buffer, ret)
		except Exception as e:
			import sys
			log_txt = '\n	'.join(self.out_buffer)
			exc_message = '{}\nLog report:\n	{}'.format(str(e), log_txt)
			rebuilt = type(e)(exc_message).with_traceback(sys.exc_info()[2])
			rebuilt.log_data = self.out_buffer
			raise rebuilt

	# # ------------------------------------------------------------------------
	# User-facing type things
	# # ------------------------------------------------------------------------

	def yp_walk_to_entry(self):
		gateway = 'https://8ch.net/fur/res/22069.html'
		step1 = self.wg.getpage(gateway)
		self.log.debug("Step 1")
		extraHeaders = {
					"Referer"       : gateway,
		}

		step2 = self.wg.getpage('https://yiff.party/zauth', addlHeaders=extraHeaders)
		self.log.debug("Step 2")

		if 'What is the name of the character pictured above?' in step2:
			self.log.info("Need to step through confirmation page.")
			params = {
				'act'       : 'anon_auth',
				'challenge' : 'anon_auth_1',
				'answer'    : 'nate',
			}
			step3 = self.wg.getpage('https://yiff.party/intermission', postData=params)
			self.log.debug("Step 3")
		else:
			step3 = step2

		if 'You have no favourite creators!' in step3:
			self.log.info("Reached home page!")
			return True
		else:
			self.log.error("Failed to reach home page!")
			self.log.error("Step 1")
			for line in step1.split("\n"):
				self.log.error("	%s", line)
			self.log.error("Step 2")
			for line in step2.split("\n"):
				self.log.error("	%s", line)
			self.log.error("Step 3")
			for line in step3.split("\n"):
				self.log.error("	%s", line)
			return False

	def yp_get_names(self):
		self.log.info("Getting available artist names!")
		ok = self.yp_walk_to_entry()
		if ok:
			data = self.wg.getpage('https://yiff.party/creators2.json', addlHeaders={"Referer" : 'https://yiff.party/'})
			return json.loads(data)
		else:
			return None

	def get_meta_from_release_soup(self, release_soup):
		retv = {}

		name = release_soup.find('span', class_='yp-info-name')
		if name:
			retv['artist_name'] = name.get_text(strip=True)

		return retv

	def get_posts_from_page(self, soup):
		posts = {}
		postdivs = soup.find_all("div", class_='yp-post')
		for postdiv in postdivs:
			post = {}
			post['id'] = postdiv['id']

			post['time']  = postdiv.find(True, class_='post-time' ).get_text(strip=True)
			titles = list(postdiv.find("span", class_='card-title').stripped_strings)
			post['title'] = titles[0] if titles else "Error: No Title"
			post['body']  = postdiv.find("div",   class_='post-body' ).get_text(strip=True)

			attachment_div = postdiv.find("div", class_='card-attachments')
			attachments = []
			if attachment_div:
				for link in attachment_div.find_all("a"):
					if link.get("href", None):
						url = urllib.parse.urljoin(self.url_base, link['href'])
						filename = link.get_text(strip=True)
						new = {'url' : url,  'fname' : filename}
						if new not in attachments:
							attachments.append(new)
					else:
						self.log.error("Missing content link from attachment card: '%s'", str(attachment_div))
						self.log.error("Relevant subsection: '%s'", str(link))

			# Somehow, some of the files don't show up
			# as attachments. Dunno why.
			action_div = postdiv.find("div", class_='card-action')
			if action_div:
				for link in action_div.find_all("a"):
					if link.get("href", None):
						url = urllib.parse.urljoin(self.url_base, link['href'])
						filename = link.get_text(strip=True)

						new = {'url' : url,  'fname' : filename}
						if new not in attachments:
							attachments.append(new)
					else:

						if link.get('class', None) == ['activator'] and link.get_text(strip=True) == 'View attachments':
							# The button is based on a <a> tag, so skip that one item.
							pass
						else:
							self.log.error("Missing content link from action_div card: '%s'", str(action_div))
							self.log.error("Relevant subsection: '%s'", str(link))
							self.log.error("Link class: '%s', link text: '%s'", link.get('class', None), link.get_text(strip=True))

			post['attachments'] = attachments

			comments = []
			for comment_div in postdiv.find_all('div', class_='yp-post-comment'):
				comment = {}
				comment['content']  = comment_div.find(True, class_='yp-post-comment-body').get_text(strip=True)
				comment['time_utc'] = comment_div.find(True, class_='yp-post-comment-time')['data-utc']
				comment['author']   = list(comment_div.find(True, class_='yp-post-comment-head').stripped_strings)[0]

				comments.append(comment)
			post['comments'] = comments

			posts[str(post['id']) + str(post['time'])] = post

		self.log.info("Found %s posts on page", len(posts))
		return posts

	def get_files_from_page(self, soup):
		files = {}
		file_divs = soup.find_all('div', class_='yp-shared-card')
		for file_div in file_divs:

			file = {}
			file['title'] = list(file_div.find(True, class_='card-title').stripped_strings)[0]
			file['post_ts'] = file_div.find(True, class_='post-time-unix').get_text(strip=True)

			content = file_div.find('div', class_='card-action')

			attachments = []
			for link in content.find_all('a'):
				if link.get("href", None):
					url = urllib.parse.urljoin(self.url_base, link['href'])
					filename = link.get_text(strip=True)
					new = {'url' : url,  'fname' : filename}
					if new not in attachments:
						attachments.append(new)
				else:
					self.log.error("Missing file link from attachment card: '%s'", str(content))
					self.log.error("Relevant subsection: '%s'", str(link))


			file['attachments'] = attachments
			files[str(file['title']) + str(file['post_ts'])] = file


		self.log.info("Found %s files on page", len(files))

		return files


	def get_releases_for_aid(self, aid):
		soup = self.wg.getSoup('https://yiff.party/{}'.format(aid), addlHeaders={"Referer" : 'https://yiff.party/'})

		# Clear out the material design icons.
		for baddiv in soup.find_all("i", class_='material-icons'):
			baddiv.decompose()

		meta = self.get_meta_from_release_soup(soup)

		try:
			posts = self.get_posts_from_page(soup)
			files = self.get_files_from_page(soup)
		except Exception as e:
			import sys
			html_txt = '\n\n' + soup.prettify() + "\n\n"
			exc_message = '{}\nFailing HTML:\n{}'.format(str(e), html_txt)
			rebuilt = type(e)(exc_message).with_traceback(sys.exc_info()[2])
			raise rebuilt

		return {
			'meta'   : meta,
			'posts' : posts,
			'files' : files,
		}

	def getFileAndName_proxy(self, *args, **kwargs):
		self.log.info("Call proxy: '%s', '%s'", args, kwargs)
		return self.wg.getFileAndName(*args, **kwargs)

	def fetch_file(self, aid, file):
		self.log.info("Fetching attachment: %s -> %s", aid, file['url'])
		file['bytes']     = 0
		try:
			# So yp provides pre-quoted, but WebGet auto-quotes, so we unquote, so we don't end up with
			# double-quoted data.
			urltmp = urllib.parse.unquote(file['url'])
			filectnt, fname = self.getFileAndName_proxy(urltmp, addlHeaders={"Referer" : 'https://yiff.party/{}'.format(aid)})
			self.log.info("Filename from request: %s", fname)
			file['header_fn'] = fname
			file['fdata']     = filectnt
			file['skipped']   = False
			file['bytes']     = len(filectnt)

			return file

		# So urllib.error.URLError is also available within urllib.request.
		except urllib.request.URLError:
			self.log.error("URLError in request!")
			for line in traceback.format_exc().split("\n"):
				self.log.error("%s", line)
			file['error']   = True
			return 0
		# This is resolved out fully in the remote execution context
		except WebRequest.Exceptions.FetchFailureError:
			self.log.error("FetchFailureError in request!")
			for line in traceback.format_exc().split("\n"):
				self.log.error("%s", line)
			file['error']   = True
			return 0

		# The serialization env causes some issues here, as it winds up
		# trying to re-serialize an exception in the logging system.
		# Anyways, just ignore that.
		except TypeError:
			self.log.error("TypeError in request!")
			for line in traceback.format_exc().split("\n"):
				self.log.error("%s", line)
			file['error']   = True
			return 0

	def set_skipped(self, releases):
		import itertools
		for item in itertools.chain(releases['posts'].values(), releases['files'].values()):
			for file in item['attachments']:
				if not any(['error' in file, 'fdata' in file]):
					file['skipped'] = True

	def push_partial_resp(self, releases, partial_resp_interface):
		self.log.info("Pushing partial response")
		self.set_skipped(releases)
		partial_resp_interface(logs=self.out_buffer, content=releases)

		# Truncate the log buffer now.
		self.out_buffer = []


	def fetch_files(self, aid, releases, have_urls, yield_chunk, total_fetch_limit, partial_resp_interface):
		self.log.info("Have %s posts", len(have_urls))
		process_chunk = copy.deepcopy(releases)

		post_keys = list(releases['posts'].keys()) + list(releases['files'].keys())
		post_keys.reverse()

		fetched       = 0
		skipped       = 0
		total         = 0
		fetched_bytes = 0

		for post_key in post_keys:
			if post_key in process_chunk['posts']:
				file_list = process_chunk['posts'][post_key]
			elif post_key in process_chunk['files']:
				file_list = process_chunk['files'][post_key]
			else:
				self.log.critical("Missing post key?")
				continue

			for file in file_list['attachments']:
				total += 1
				file['skipped']   = True

				if file['url'] in have_urls:
					self.log.info("Have file from URL %s, nothing to do", file['url'])
					file['skipped'] = True
					skipped += 1
				else:
					self.fetch_file(aid, file)
					self.log.info("fetch_file() returned %s bytes, file keys: %s, skipped: %s",
							file['bytes'],
							list(file.keys()),
							file['skipped'] if 'skipped' in file else "unknown"
						)
					fetched       += 1
					fetched_bytes += file['bytes']

			self.log.info("Fetched %s bytes of data so far", fetched_bytes)
			if fetched_bytes > yield_chunk:
				self.log.info("Incrememtal return!")
				self.push_partial_resp(process_chunk, partial_resp_interface)
				process_chunk = copy.deepcopy(releases)
				fetched_bytes = 0

				# Rate limiting.
				time.sleep(60 * 15)

			if total_fetch_limit and fetched > total_fetch_limit:
				break

		self.log.info("Finished fetch_files step.")
		self.log.info("Skipped %s files, fetched %s files. %s files total (%s bytes).", skipped, fetched, total, fetched_bytes)

		return process_chunk


	def yp_get_content_for_artist(self, aid, have_urls, yield_chunk=16777216, total_fetch_limit=None, partial_resp_interface=None, extra_meta=None):

		self.log.info("Getting content for artist: %s", aid)
		self.log.info("partial_resp_interface: %s", partial_resp_interface)


		# <function RpcHandler.partial_response.<locals>.partial_capture at 0x7fd4b260fd08>
		if "partial_capture" in str(partial_resp_interface):
			self.log.info("Partials interface!")

		else:
			raise ValueError

		ok = self.yp_walk_to_entry()
		if not ok:
			return "Error! Failed to access entry!"

		releases = self.get_releases_for_aid(aid)

		releases['extra_meta'] = extra_meta

		releases = self.fetch_files(aid, releases, have_urls, yield_chunk, total_fetch_limit, partial_resp_interface)
		# else:
		self.set_skipped(releases)
		self.log.info("Content retreival finished.")

		return releases

	def _go(self, mode, **kwargs):

		if mode == 'yp_get_names':
			return self.yp_get_names()
		elif mode == "yp_get_content_for_artist":
			return self.yp_get_content_for_artist(**kwargs)
		elif mode == "plain_web_get":
			return self.getFileAndName_proxy(**kwargs)
		else:
			self.log.error("Unknown mode: '%s'", mode)
			return "Unknown mode: '%s' -> Kwargs: '%s'" % (mode, kwargs)


