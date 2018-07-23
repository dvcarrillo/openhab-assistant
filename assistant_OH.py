#!/usr/bin/env python3
# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Run a voice recognizer that uses the Google Assistant Library and TTS, with 
customized commands for interacting with OpenHAB 2 via REST

The Google Assistant Library has direct access to the audio API, so this Python
code doesn't need to record audio. 

Hot word detection "OK, Google" and button push are supported.

The Google Assistant Library can be installed with:
    env/bin/pip install google-assistant-library==0.0.2

It is available for Raspberry Pi 2/3 only; Pi Zero is not supported.

Modified from Google AIY demo scripts by David Vargas (https://github.com/dvcarrillo)
"""

import logging
import subprocess
import threading
import requests
import sys

import aiy.assistant.auth_helpers
import aiy.assistant.device_helpers
import aiy.audio
import aiy.voicehat
from google.assistant.library import Assistant
from google.assistant.library.event import EventType

# ---- CONFIGURATION ----
# openHAB server location
openhab_ip = "localhost"
openhab_port = "8080"

# Set the group containing all the lights
all_lights_group = 'Lights_ALL'

# Set the Items on OpenHAB related to your light bulbs
# The lights_ids array will be used for identifying each light in the spoken commands
light_colors = ['hue_0210_00178828e0d0_1_color']
light_color_temps = ['hue_0210_00178828e0d0_1_color_temperature']
lights_ids = ['office']     # Example: "turn on the office light"

# Hotwords that triggers the OpenHAB actions
custom_hotword = 'home'

# Show debug information (0 = false, 1 = true)
debug = 1
# -----------------------

# The en-GB voice is clearer than the default en-US
aiy.i18n.set_language_code('en-GB')

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
)

# -- OpenHAB 2 commands using OpenHAB REST API --

def openhab_send(item, state):
    url = 'http://' + openhab_ip + ':' + openhab_port + '/rest/items/' + item
    headers = { 'content-type': 'text/plain',
                'accept': 'application/json' }
    r = requests.post(url, headers=headers, data=state)

    if (debug):
        print('REQUEST [POST]: ' + url + ' STATE: ' + state)

    if r.status_code == 200:
        aiy.audio.say('OK')
    elif r.status_code == 400:
        if (debug):
            print('ERROR [HTTP 400]: ' + r.text)
        aiy.audio.say('There has been an error: bad command')
    elif r.status_code == 404:
        if (debug):
            print('ERROR [HTTP 404]: ' + r.text)
        aiy.audio.say('There has been an error: unknown item')
    else:
        aiy.audio.say('Command failed')

def openhab_get_state(item):
    url = 'http://' + openhab_ip + ':' + openhab_port + '/rest/items/' + item + '/state'
    r = requests.get(url)
    return r.text

# -- Power management commands --

def power_off_pi():
    aiy.audio.say('Powering off the system. Good bye!')
    subprocess.call('sudo shutdown now', shell=True)

def reboot_pi():
    aiy.audio.say('Rebooting the system. Hold on!')
    subprocess.call('sudo reboot', shell=True)

def not_recognized():
    aiy.audio.say('Sorry, I cannot do that yet')

def device_not_found():
    aiy.audio.say('Sorry, I don\'t know that device')

def test_speech():
    aiy.audio.say('Hello. This is a Text to Speech test.')

# -- Helper functions -- 

def any_idx(iterable):
    idx = 0
    for element in iterable:
        if element:
            return idx
        else:
            idx = idx + 1

# -- Class MyAssistant --

class MyAssistant(object):
    """
    An assistant that runs in the background.

    The Google Assistant Library event loop blocks the running thread entirely.
    To support the button trigger, we need to run the event loop in a separate
    thread. Otherwise, the on_button_pressed() method will never get a chance to
    be invoked.
    """
    def __init__(self):
        self._task = threading.Thread(target=self._run_task)
        self._can_start_conversation = False
        self._assistant = None

    def start(self):
        """
        Starts the assistant.

        Starts the assistant event loop and begin processing events.
        """
        self._task.start()

    def _run_task(self):
        credentials = aiy.assistant.auth_helpers.get_assistant_credentials()
        model_id, device_id = aiy.assistant.device_helpers.get_ids(credentials)
        with Assistant(credentials, model_id) as assistant:
            self._assistant = assistant
            for event in assistant.start():
                self._process_event(event)

    # State management and event processing
    def _process_event(self, event):
        status_ui = aiy.voicehat.get_status_ui()
        if event.type == EventType.ON_START_FINISHED:
            status_ui.status('ready')
            self._can_start_conversation = True
            # Start the voicehat button trigger.
            aiy.voicehat.get_button().on_press(self._on_button_pressed)
            if sys.stdout.isatty():
                print('\nSay "OK, Google" or press the button, then speak. '
                      '\nTrigger the openHAB actions by saying \"' + custom_hotword + 
                      '\" at the beginning of each command.'
                      '\nPress Ctrl+C to quit.\n')

        elif event.type == EventType.ON_CONVERSATION_TURN_STARTED:
            self._can_start_conversation = False
            status_ui.status('listening')

        elif event.type == EventType.ON_END_OF_UTTERANCE:
            status_ui.status('thinking')

        elif event.type == EventType.ON_RECOGNIZING_SPEECH_FINISHED and event.args:
            print('You said:', event.args['text'])
            text = event.args['text'].lower()

            # CHECK HOTWORD
            if text.startswith(custom_hotword):
                self._assistant.stop_conversation()
                text = text + " "

                # CHECK ACTION
                # Power, turn, set, change
                if any(token in text for token in (' turn ', ' power ', ' set ', ' change ')):
                    # CHECK DEVICE
                    # For all the lights
                    if ' all ' in text and ' lights ' in text:
                        if ' on ' in text:
                            openhab_send(all_lights_group, 'ON')
                        elif ' off ' in text:
                            openhab_send(all_lights_group, 'OFF')
                        else:
                            not_recognized()

                    # For a specific light
                    elif ' light ' in text:
                        # Get the index of the mentioned item in the light arrays
                        idx = any_idx(token in text for token in lights_ids)
                        if (idx != None):
                            direct_to_color = light_colors[idx]
                            direct_to_color_temp = light_color_temps[idx]
                            current_state = openhab_get_state(direct_to_color).split(',')

                            if ' on ' in text:
                                openhab_send(direct_to_color, 'ON')
                            elif ' off ' in text:
                                openhab_send(direct_to_color, 'OFF')
                            elif ' red ' in text:
                                new_state = "0,100," + current_state[2]
                                openhab_send(direct_to_color, new_state)
                            elif ' yellow ' in text:
                                new_state = "100,100," + current_state[2]
                                openhab_send(direct_to_color, new_state)
                            elif ' blue ' in text:
                                new_state = "260,100," + current_state[2]
                                openhab_send(direct_to_color, new_state)
                            elif ' pink ' in text:
                                new_state = "340,100," + current_state[2]
                                openhab_send(direct_to_color, new_state)
                            elif ' green ' in text:
                                new_state = "140,100," + current_state[2]
                                openhab_send(direct_to_color, new_state)
                            elif ' cool ' in text:
                                openhab_send(direct_to_color_temp, "0")
                            elif ' warm ' in text:
                                openhab_send(direct_to_color_temp, "100")
                            elif ' natural ' in text:
                                openhab_send(direct_to_color_temp, "50")
                            else:
                                not_recognized()
                        else:
                            device_not_found()

                    # For the system
                    elif ' system ' in text:
                        if ' off ' in text:
                            power_off_pi()
                    else:
                        not_recognized()

                # Increase, raise
                elif any(token in text for token in (' increase ', ' raise ')):
                    if ' brightness ' in text and 'light' in text:
                        idx = any_idx(token in text for token in lights_ids)
                        if (idx != None):
                            direct_to_color = light_colors[idx]
                            current_state = openhab_get_state(direct_to_color).split(',')

                            new_brightness = int(current_state[2]) + 25
                            if (new_brightness > 100):
                                new_brightness = 100
                            
                            new_state = current_state[0] + ',' + current_state[1] + ',' + str(new_brightness)
                            openhab_send(direct_to_color, new_state)
                        else:
                            device_not_found()
                    else:
                        not_recognized()

                # Decrease, reduce
                elif any(token in text for token in (' decrease ', ' reduce ')):
                    if ' brightness ' in text and 'light' in text:
                        idx = any_idx(token in text for token in lights_ids)
                        if (idx != None):
                            direct_to_color = light_colors[idx]
                            current_state = openhab_get_state(direct_to_color).split(',')
                           
                            new_brightness = int(current_state[2]) - 25
                            if (new_brightness < 0):
                                new_brightness = 0
                            
                            new_state = current_state[0] + ',' + current_state[1] + ',' + str(new_brightness)
                            openhab_send(direct_to_color, new_state)
                        else:
                            device_not_found()
                    else:
                        not_recognized()

                # Reboot, restart
                elif any(token in text for token in (' reboot ', ' restart ')):
                    if ' system ' in text:
                        reboot_pi()
                else:
                    not_recognized()

        elif event.type == EventType.ON_CONVERSATION_TURN_FINISHED:
            status_ui.status('ready')
            self._can_start_conversation = True

        elif event.type == EventType.ON_ASSISTANT_ERROR and event.args and event.args['is_fatal']:
            sys.exit(1)

    def _on_button_pressed(self):
        # Check if we can start a conversation. 'self._can_start_conversation'
        # is False when either:
        # 1. The assistant library is not yet ready; OR
        # 2. The assistant library is already in a conversation.
        if self._can_start_conversation:
            self._assistant.start_conversation()

def main():
    MyAssistant().start()

if __name__ == '__main__':
    main()
