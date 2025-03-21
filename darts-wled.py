import os
import json
import platform
import random
import argparse
import threading
import logging
from color_constants import colors as WLED_COLORS
import time
import requests
import socketio
import websocket


sh = logging.StreamHandler()
sh.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
sh.setFormatter(formatter)
logger=logging.getLogger()
logger.handlers.clear()
logger.setLevel(logging.INFO)
logger.addHandler(sh)



http_session = requests.Session()
http_session.verify = False
sio = socketio.Client(http_session=http_session, logger=True, engineio_logger=True)


VERSION = '1.6.0'

DEFAULT_EFFECT_BRIGHTNESS = 175
DEFAULT_EFFECT_IDLE = 'solid|lightgoldenrodyellow'

DEFAULT_EFFECT_SEGMENT_THROW = "solid|yellow1"
DEFAULT_LEDS_PER_METER = 60
DIAMETER_3DEME_WLED = 74.5

WLED_EFFECT_LIST_PATH = '/json/eff'
EFFECT_PARAMETER_SEPARATOR = "|"
BOGEY_NUMBERS = [169, 168, 166, 165, 163, 162, 159]
SUPPORTED_CRICKET_FIELDS = [15, 16, 17, 18, 19, 20, 25]
SUPPORTED_GAME_VARIANTS = ['X01', 'Cricket', 'Random Checkout']



def ppi(message, info_object = None, prefix = '\r\n'):
    logger.info(prefix + str(message))
    if info_object is not None:
        logger.info(str(info_object))
    
def ppe(message, error_object):
    ppi(message)
    if DEBUG:
        logger.exception("\r\n" + str(error_object))



def connect_wled(we):
    def process(*args):
        global WS_WLEDS
        websocket.enableTrace(False)
        wled_host = we
        if we.startswith('ws://') == False:
            wled_host = 'ws://' + we + '/ws'
        ws = websocket.WebSocketApp(wled_host,
                                    on_open = on_open_wled,
                                    on_message = on_message_wled,
                                    on_error = on_error_wled,
                                    on_close = on_close_wled)
        WS_WLEDS.append(ws)

        ws.run_forever()
    threading.Thread(target=process).start()

def on_open_wled(ws):
    control_wled(IDLE_EFFECT, 'CONNECTED TO WLED ' + str(ws.url), bss_requested=False)

def on_message_wled(ws, message):
    def process(*args):
        try:
            global lastMessage
            global waitingForIdle
            global waitingForBoardStart

            m = json.loads(message)

            # only process incoming messages of primary wled-endpoint
            if 'info' not in m or m['info']['ip'] != WLED_ENDPOINT_PRIMARY:
                return

            if lastMessage != m:
                lastMessage = m

                # ppi(json.dumps(m, indent = 4, sort_keys = True))

                # if 'state' in m :
                #     ppi('server ps: ' + str(m['state']['ps']))
                #     ppi('server pl: ' + str(m['state']['pl']))
                #     ppi('server fx: ' + str(m['state']['seg'][0]['fx']))

                if 'state' in m and waitingForIdle == True:

                    # [({'seg': {'fx': '0', 'col': [[250, 250, 210, 0]]}, 'on': True}, DURATION)]
                    (ide, duration) = IDLE_EFFECT[0]
                    seg = m['state']['seg'][0]

                    is_idle = False
                    if 'ps' in ide and ide['ps'] == str(m['state']['ps']):
                        is_idle = True
                    elif ide['seg']['fx'] == str(seg['fx']) and m['state']['ps'] == -1 and m['state']['pl'] == -1:
                        is_idle = True
                        if 'col' in ide['seg'] and ide['seg']['col'][0] not in seg['col']:
                            is_idle = False
                        if 'sx' in ide['seg'] and ide['seg']['sx'] != str(seg['sx']):
                            is_idle = False
                        if 'ix' in ide['seg'] and ide['seg']['ix'] != str(seg['ix']):
                            is_idle = False
                        if 'pal' in ide['seg'] and ide['seg']['pal'] != str(seg['pal']):
                            is_idle = False

                    if is_idle == True:
                        # ppi('Back to IDLE')
                        waitingForIdle = False
                        if waitingForBoardStart == True:
                            waitingForBoardStart = False
                            sio.emit('message', 'board-start:' + str(BOARD_STOP_START))


        except Exception as e:
            ppe('WS-Message failed: ', e)

    threading.Thread(target=process).start()

def on_close_wled(ws, close_status_code, close_msg):
    try:
        ppi("Websocket [" + str(ws.url) + "] closed! " + str(close_msg) + " - " + str(close_status_code))
        ppi("Retry : %s" % time.ctime())
        time.sleep(3)
        connect_wled(ws.url)
    except Exception as e:
        ppe('WS-Close failed: ', e)

def on_error_wled(ws, error):
    ppe('WS-Error ' + str(ws.url) + ' failed: ', error)

def control_wled(effect_list, ptext, bss_requested = True, is_win = False):
    global waitingForIdle
    global waitingForBoardStart

    if is_win == True and BOARD_STOP_AFTER_WIN == 1:
        sio.emit('message', 'board-reset')
        ppi('Board reset after win')
        time.sleep(0.15)

    # if bss_requested == True and (BOARD_STOP_START != 0.0 or is_win == True): 
    # changed becouse of aditional -BSW parameter
    if bss_requested == True and BOARD_STOP_START != 0.0:
        waitingForBoardStart = True
        sio.emit('message', 'board-stop')
        if is_win == 1:
            time.sleep(0.15)

    #Bord Stop after Win
    if BOARD_STOP_AFTER_WIN != 0 and is_win == True:
        waitingForBoardStart = True
        sio.emit('message', 'board-stop')
        if is_win == 1:
            time.sleep(0.15)
    if effect_list == 'off':
        tempstate = '{"on":false}'
        state = json.loads(tempstate)
        broadcast(state)
    else:
        (state, duration) = get_state(effect_list)
        state.update({'on': True})
        broadcast(state)

    ppi(ptext + ' - WLED: ' + str(state))

    if bss_requested == True:
        waitingForIdle = True

        wait = EFFECT_DURATION
        if duration is not None:
            wait = duration

        if(wait > 0):
            time.sleep(wait)
            (state, duration) = get_state(IDLE_EFFECT)
            state.update({'on': True})
            broadcast(state)

def broadcast(data):
    global WS_WLEDS

    for wled_ep in WS_WLEDS:
        try:
            # ppi("Broadcasting to " + str(wled_ep))
            threading.Thread(target=broadcast_intern, args=(wled_ep, data)).start()
        except:
            continue

def broadcast_intern(endpoint, data):
    try:
        endpoint.send(json.dumps(data))
    except:
        return



def get_state(effect_list):
    if effect_list == ["x"] or effect_list == ["X"]:
        # TODO: add more rnd parameter
        return {"seg": {"fx": str(random.choice(WLED_EFFECT_ID_LIST))} }
    else:
        return random.choice(effect_list)

def parse_segment_effects_argument(segment_effects_arguments, segment, freeze="true"):
    if segment_effects_arguments == None or segment_effects_arguments == ["x"] or segment_effects_arguments == ["X"]:
        return segment_effects_arguments

    leds = list()
    if segment in [25, 50]:
        for seg_number in INNER_LEDS_PER_SECTION:
            leds.extend(INNER_LEDS_PER_SECTION[seg_number])

        for seg_number in OUTER_LEDS_PER_SECTION:
            leds.extend(OUTER_LEDS_PER_SECTION[seg_number])
    else:
        leds = INNER_LEDS_PER_SECTION[segment] if WLED_START_FACING == 1 else OUTER_LEDS_PER_SECTION[segment]
        leds += (OUTER_LEDS_PER_SECTION[segment] if WLED_START_FACING == 1 else INNER_LEDS_PER_SECTION[segment]) or []

    leds.sort()
    ppi(leds)

    color = list()
    for effect in segment_effects_arguments:
        try:
            effect_params = effect.split(EFFECT_PARAMETER_SEPARATOR)

            for ep in effect_params[1:]:
                param_key = ep[0].strip().lower()
                param_value = ep[1:].strip().lower()

                colors = WLED_COLORS[param_key + param_value]
                color = list(colors)

        except Exception as e:
            ppe("Failed to parse event-configuration for segments: ", e)
            continue

    led_ranges = []
    current_range = [leds[0]]

    for i in range(1, len(leds)):
        if leds[i] == leds[i - 1] + 1:
            current_range.append(leds[i])
        else:
            led_ranges.append(current_range)
            current_range = [leds[i]]
    led_ranges.append(current_range)

    ppi(led_ranges)

    hex_segments = []
    for led_range in led_ranges:
        hex_segments.append(led_range[0])
        hex_segments.append(led_range[-1])
        hex_segments.append(color)

    ppi("segment_effects_arguments: " + str(segment_effects_arguments))
    ppi("hex_segments: " + str(hex_segments))

    data = {"seg": []}
    filler_segments = [{"on": "true"} for _ in range(int(WLED_RING_SEGMENTS[0]))]
    data["seg"] = filler_segments

    if len(WLED_RING_SEGMENTS) == 1:
        data["seg"].append( {"id": WLED_RING_SEGMENTS[0], "bri": 255, "frz": freeze, "i": str(hex_segments) } )
    elif len(WLED_RING_SEGMENTS) == 2:
            data["seg"].append( { "id": WLED_RING_SEGMENTS[0], "bri": 255, "frz": freeze, "i": str(hex_segments) } )
            data["seg"].append( { "id": WLED_RING_SEGMENTS[1], "bri": 255, "frz": freeze, "i": str(hex_segments) } )


    parsed_list = list()
    parsed_list.append((data, None))
    ppi(parsed_list)
    return parsed_list

def parse_effects_argument(effects_argument, custom_duration_possible = True):
    if effects_argument == None or effects_argument == ["x"] or effects_argument == ["X"]:
        return effects_argument

    parsed_list = list()
    for effect in effects_argument:
        try:
            effect_params = effect.split(EFFECT_PARAMETER_SEPARATOR)
            effect_declaration = effect_params[0].strip().lower()

            custom_duration = None

            # preset/ playlist
            if effect_declaration == 'ps':
                state = {effect_declaration : effect_params[1] }
                if custom_duration_possible == True and len(effect_params) >= 3 and effect_params[2].isdigit() == True:
                    custom_duration = int(effect_params[2])
                parsed_list.append((state, custom_duration))
                continue

            # effect by ID
            elif effect_declaration.isdigit() == True:
                effect_id = effect_declaration

            # effect by name
            else:
                effect_id = str(WLED_EFFECTS.index(effect_declaration))



            # everying else .. can have different positions

            # p30
            # ie: "61-120" "29|blueviolet|s255|i255|red1|green1"

            seg = {"fx": effect_id}

            colours = list()
            for ep in effect_params[1:]:

                param_key = ep[0].strip().lower()
                param_value = ep[1:].strip().lower()

                # s = speed (sx)
                if param_key == 's' and param_value.isdigit() == True:
                    seg["sx"] = param_value

                # i = intensity (ix)
                elif param_key == 'i' and param_value.isdigit() == True:
                    seg["ix"] = param_value

                # p = palette (pal)
                elif param_key == 'p' and param_value.isdigit() == True:
                    seg["pal"] = param_value

                # du (custom duration)
                elif custom_duration_possible == True and param_key == 'd' and param_value.isdigit() == True:
                    custom_duration = int(param_value)

                # colors 1 - 3 (primary, secondary, tertiary)
                else:
                    color = WLED_COLORS[param_key + param_value]
                    color = list(color)
                    color.append(0)
                    colours.append(color)


            if len(colours) > 0:
                seg["col"] = colours

            parsed_list.append(({"seg": seg}, custom_duration))

        except Exception as e:
            ppe("Failed to parse event-configuration: ", e)
            continue

    return parsed_list

def parse_score_area_effects_argument(score_area_effects_arguments):
    if score_area_effects_arguments == None:
        return score_area_effects_arguments

    area = score_area_effects_arguments[0].strip().split('-')
    if len(area) == 2 and area[0].isdigit() and area[1].isdigit():
        return ((int(area[0]), int(area[1])), parse_effects_argument(score_area_effects_arguments[1:]))
    else:
        raise Exception(score_area_effects_arguments[0] + ' is not a valid score-area')



def process_lobby(msg):
    if msg['action'] == 'player-joined' and PLAYER_JOINED_EFFECTS is not None:
        control_wled(PLAYER_JOINED_EFFECTS, 'Player joined!')

    elif msg['action'] == 'player-left' and PLAYER_LEFT_EFFECTS is not None:
        control_wled(PLAYER_LEFT_EFFECTS, 'Player left!')

def process_variant_x01(msg):
    if msg['event'] == 'darts-thrown':
        val = str(msg['game']['dartValue'])
        if SCORE_EFFECTS[val] is not None:
            control_wled(SCORE_EFFECTS[val], 'Darts-thrown: ' + val)
            ppi(SCORE_EFFECTS[val])
        else:
            area_found = False
            ival = int(val)
            for SAE in SCORE_AREA_EFFECTS:
                if SCORE_AREA_EFFECTS[SAE] is not None:
                    ((area_from, area_to), AREA_EFFECTS) = SCORE_AREA_EFFECTS[SAE]

                    if ival >= area_from and ival <= area_to:
                        control_wled(AREA_EFFECTS, 'Darts-thrown: ' + val)
                        area_found = True
                        break
            if area_found == False:
                ppi('Darts-thrown: ' + val + ' - NOT configured!')

    elif msg['event'] == 'dart1-thrown' or msg['event'] == 'dart2-thrown' or msg['event'] == 'dart3-thrown':
        control_wled(IDLE_EFFECT, 'Board started', bss_requested=False)
        seg = str(msg['game']['segment'])
        control_wled(SEGMENT_HIT_EFFECTS[seg], 'Seg: ' + seg, bss_requested=False)

    elif msg['event'] == 'darts-pulled':
        if EFFECT_DURATION == 0:
            ppi(IDLE_EFFECT)
            control_wled(IDLE_EFFECT, 'Darts-pulled', bss_requested=False)

    elif msg['event'] == 'busted' and BUSTED_EFFECTS is not None:
        control_wled(BUSTED_EFFECTS, 'Busted!')

    elif msg['event'] == 'game-won' and GAME_WON_EFFECTS is not None:
        if HIGH_FINISH_ON is not None and int(msg['game']['dartsThrownValue']) >= HIGH_FINISH_ON and HIGH_FINISH_EFFECTS is not None:
            control_wled(HIGH_FINISH_EFFECTS, 'Game-won - HIGHFINISH', is_win=True)
        else:
            control_wled(GAME_WON_EFFECTS, 'Game-won', is_win=True)

    elif msg['event'] == 'match-won' and MATCH_WON_EFFECTS is not None:
        if HIGH_FINISH_ON is not None and int(msg['game']['dartsThrownValue']) >= HIGH_FINISH_ON and HIGH_FINISH_EFFECTS is not None:
            control_wled(HIGH_FINISH_EFFECTS, 'Match-won - HIGHFINISH', is_win=True)
        else:
            control_wled(MATCH_WON_EFFECTS, 'Match-won', is_win=True)

    elif msg['event'] == 'match-started':
        if EFFECT_DURATION == 0:
            control_wled(IDLE_EFFECT, 'Match-started', bss_requested=False)

    elif msg['event'] == 'game-started':
        if EFFECT_DURATION == 0:
            control_wled(IDLE_EFFECT, 'Game-started', bss_requested=False)

def process_board_status(msg):
    if msg['event'] == 'Board Status':
        if msg['data']['status'] == 'Board Stopped' and BOARD_STOP_EFFECT is not None and (BOARD_STOP_START == 0.0 or BOARD_STOP_START is None):
           control_wled(BOARD_STOP_EFFECT, 'Board-stopped', bss_requested=False)
        #    control_wled('test', 'Board-stopped', bss_requested=False)
        elif msg['data']['status'] == 'Board Started':
            control_wled(IDLE_EFFECT, 'Board started', bss_requested=False)
        elif msg['data']['status'] == 'Manual reset':
            control_wled(IDLE_EFFECT, 'Manual reset', bss_requested=False)
        elif msg['data']['status'] == 'Takeout Started' and TAKEOUT_EFFECT is not None:
            control_wled(TAKEOUT_EFFECT, 'Takeout Started', bss_requested=False)
        elif msg['data']['status'] == 'Takeout Finished':
            control_wled(IDLE_EFFECT, 'Takeout Finished', bss_requested=False)
        elif msg['data']['status'] == 'Calibration Started' and CALIBRATION_EFFECT is not None:
            control_wled(CALIBRATION_EFFECT, 'Calibration Started', bss_requested=False)
        elif msg['data']['status'] == 'Calibration Finished':
            control_wled(IDLE_EFFECT, 'Calibration Finished', bss_requested=False)

def process_wled_off():
    if WLED_OFF is not None and WLED_OFF == 1:
        control_wled('off', 'WLED Off', bss_requested=False)

@sio.event
def connect():
    ppi('CONNECTED TO DATA-FEEDER ' + sio.connection_url)

@sio.event
def connect_error(data):
    if DEBUG:
        ppe("CONNECTION TO DATA-FEEDER FAILED! " + sio.connection_url, data)

@sio.event
def message(msg):
    try:
        # ppi(message)
        if('game' in msg and 'mode' in msg['game']):
            mode = msg['game']['mode']
            if mode == 'X01' or mode == 'Cricket' or mode == 'Random Checkout':
                process_variant_x01(msg)
            # elif mode == 'Cricket':
            #     process_match_cricket(msg)
        elif('event' in msg and msg['event'] == 'lobby'):
            process_lobby(msg)
        elif('event' in msg and msg['event'] == 'Board Status'):
            process_board_status(msg)
        elif('event' in msg and msg['event'] == 'match-ended'):
            process_wled_off()

    except Exception as e:
        ppe('DATA-FEEDER Message failed: ', e)

@sio.event
def disconnect():
    ppi('DISCONNECTED FROM DATA-FEEDER ' + sio.connection_url)



def connect_data_feeder():
    try:
        server_host = CON.replace('ws://', '').replace('wss://', '').replace('http://', '').replace('https://', '')
        server_url = 'ws://' + server_host
        sio.connect(server_url, transports=['websocket'])
    except Exception:
        try:
            server_url = 'wss://' + server_host
            sio.connect(server_url, transports=['websocket'], retry=True, wait_timeout=3)
        except Exception:
            pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-CON", "--connection", default="127.0.0.1:8079", required=False, help="Connection to data feeder")
    ap.add_argument("-WEPS", "--wled_endpoints", required=True, nargs='+', help="Url(s) to wled instance(s)")
    ap.add_argument("-DU", "--effect_duration", type=int, default=0, required=False, help="Duration of a played effect in seconds. After that WLED returns to idle. 0 means infinity duration.")
    ap.add_argument("-BSS", "--board_stop_start", default=0.0, type=float, required=False, help="If greater than 0.0 stops the board before playing effect")
    ap.add_argument("-BRI", "--effect_brightness", type=int, choices=range(1, 256), default=DEFAULT_EFFECT_BRIGHTNESS, required=False, help="Brightness of current effect")
    ap.add_argument("-HFO", "--high_finish_on", type=int, choices=range(1, 171), default=None, required=False, help="Individual score for highfinish")
    ap.add_argument("-HF", "--high_finish_effects", default=None, required=False, nargs='*', help="WLED effect-definition when high-finish occurs")
    ap.add_argument("-IDE", "--idle_effect", default=[DEFAULT_EFFECT_IDLE], required=False, nargs='*', help="WLED effect-definition when waiting for throw")
    ap.add_argument("-G", "--game_won_effects", default=None, required=False, nargs='*', help="WLED effect-definition when game won occurs")
    ap.add_argument("-M", "--match_won_effects", default=None, required=False, nargs='*', help="WLED effect-definition when match won occurs")
    ap.add_argument("-B", "--busted_effects", default=None, required=False, nargs='*', help="WLED effect-definition when bust occurs")
    ap.add_argument("-PJ", "--player_joined_effects", default=None, required=False, nargs='*', help="WLED effect-definition when player-join occurs")
    ap.add_argument("-PL", "--player_left_effects", default=None, required=False, nargs='*', help="WLED effect-definition when player-left occurs")
    for v in range(0, 181):
        val = str(v)
        ap.add_argument("-S" + val, "--score_" + val + "_effects", default=None, required=False, nargs='*', help="WLED effect-definition for score " + val)
    for a in range(1, 13):
        area = str(a)
        ap.add_argument("-A" + area, "--score_area_" + area + "_effects", default=None, required=False, nargs='*', help="WLED effect-definition for score-area")
    
    ap.add_argument("-DEB", "--debug", type=int, choices=range(0, 2), default=False, required=False, help="If '1', the application will output additional information")
    ap.add_argument("-BSW", "--board_stop_after_win", type=int, choices=range(0, 2), default=True, required=False, help="Let the board stop after winning the match check it to activate the board stop")
    # NEEDS TO BE MIGRATED!!!!!
    ap.add_argument("-BSE", "--board_stop_effect", default=None, required=False, nargs='*', help="WLED effect-definition when Board is stopped")
    ap.add_argument("-TOE", "--takeout_effect", default=None, required=False, nargs='*', help="WLED effect-definition when Takeout will be performed")
    ap.add_argument("-CE", "--calibration_effect", default=None, required=False, nargs='*', help="WLED effect-definition when Calibration will be performed")
    ap.add_argument("-OFF", "--wled_off", type=int, choices=range(0, 2), default=False, required=False, help="Turns WLED Off after game")

    ap.add_argument("-D", "--diameter_wled_stripe", type=float, default=DIAMETER_3DEME_WLED, required=False, help="Diameter of the mounted WLED Stripe")
    ap.add_argument("-LPM", "--leds_per_meter", type=int, choices=range(1, 150), default=DEFAULT_LEDS_PER_METER, required=False, help="Amount of LEDs per meter of the mounted WLED Stripe")
    ap.add_argument("-SOL", "--start_offset_leds", type=int, default=0, required=False, help="Offset LEDs from line between 20 and 1 to beginning of the mounted WLED Stripe")
    ap.add_argument("-EOL", "--end_offset_leds", type=int, default=0, required=False, help="Number of missing LEDS at the end of the mounted WLED Stripe to the start, if the stripe is not a full circle, only needed when WLED forms 2 circles.")
    ap.add_argument("-ALNS", "--additional_leds_neighbour_segment", type=int, default=0, required=False, help="If a segment is hit, also x LEDs from the neighbour segments will be lighten up ")

    ap.add_argument("-WMC", "--wled_mount_clockwise", type=int, choices=range(0, 2), default=True, required=False, help="Direction of the mounted WLED Stripe: clockwise = 1, counter clockwise = 0")
    ap.add_argument("-WSF", "--wled_start_facing", type=int, choices=range(0, 2), default=1, required=False, help="Facing of the start from the mounted WLED Stripe faces: inside = 1, outside = 0")
    ap.add_argument("-WRS", "--wled_ring_segments", default=0, required=False, nargs='*', help="Segment IDs in WLED that contain the LEDS in the ring. E.G. All Leds in one Segment, ID = X, Split in outer and inner ring, IDs = X-Y")
    ap.add_argument("-WC", "--wled_cirlces", type=int, choices=range(0, 3), default=0, required=False, help="Amount of Cirlces, your WLED Stripe forms: E.G. 3DeMe-WLED-Ring: 2, WLED around surrond: 1 to max 2")
    ap.add_argument("-WSCD", "--wled_second_circle_direction", type=int, choices=range(0, 2), default=1, required=False, help="If 2 Circles, after the first circle: LEDs continue in same direction: 1, LEDs continue in opposite direction: 0")

    for s in range(1, 21):
        seg = str(s)
        ap.add_argument("-SEG" + seg, "--segment_" + seg + "_effects", default=None, required=False, nargs='*', help="WLED effect-definition if the darts land in the segment: " + seg)
    ap.add_argument("-SEG25", "--segment_25_effects", default=None, required=False, nargs='*', help="WLED effect-definition if the darts land in the segment: 25/BULL")
    ap.add_argument("-SEG50", "--segment_50_effects", default=None, required=False, nargs='*', help="WLED effect-definition if the darts land in the segment: 50/BULLSEYE")


    args = vars(ap.parse_args())


    global WS_WLEDS
    WS_WLEDS = list()

    global lastMessage
    lastMessage = None

    global waitingForIdle
    waitingForIdle = False

    global waitingForBoardStart
    waitingForBoardStart = False

    # ppi('Started with following arguments:')
    # ppi(json.dumps(args, indent=4))

    osType = platform.system()
    osName = os.name
    osRelease = platform.release()
    ppi('\r\n', None, '')
    ppi('##########################################', None, '')
    ppi('       WELCOME TO DARTS-WLED', None, '')
    ppi('##########################################', None, '')
    ppi('VERSION: ' + VERSION, None, '')
    ppi('RUNNING OS: ' + osType + ' | ' + osName + ' | ' + osRelease, None, '')
    ppi('SUPPORTED GAME-VARIANTS: ' + " ".join(str(x) for x in SUPPORTED_GAME_VARIANTS), None, '')
    ppi('DONATION: bitcoin:bc1q8dcva098rrrq2uqhv38rj5hayzrqywhudvrmxa', None, '')
    ppi('\r\n', None, '')

    DEBUG = args['debug']
    CON = args['connection']
    WLED_ENDPOINTS = list(args['wled_endpoints'])
    WLED_ENDPOINT_PRIMARY = args['wled_endpoints'][0]
    EFFECT_DURATION = args['effect_duration']
    BOARD_STOP_START = args['board_stop_start']
    BOARD_STOP_AFTER_WIN = args['board_stop_after_win']
    EFFECT_BRIGHTNESS = args['effect_brightness']
    HIGH_FINISH_ON = args['high_finish_on']
    WLED_OFF = args['wled_off']
    

    DIAMETER_WLED = args['diameter_wled_stripe']
    LEDS_PER_METER = args['leds_per_meter']
    START_OFFSET_LEDS = args['start_offset_leds']
    END_OFFSET_LEDS = args['end_offset_leds']

    WLED_MOUNT_CLOCKWISE = args['wled_mount_clockwise']
    WLED_START_FACING = args['wled_start_facing']
    WLED_RING_SEGMENTS = [int(x) for x in args['wled_ring_segments'][0].split('-')]

    WLED_CIRLCES = int(args['wled_cirlces'])
    WLED_SECOND_CIRCLE_DIRECTION = args['wled_second_circle_direction']

    ppi("Durchmesser: " + str(DIAMETER_WLED))
    ppi("LEDs/Meter: " + str(LEDS_PER_METER))
    ppi("START_OFFSET_LEDS: " + str(START_OFFSET_LEDS))
    ppi("END_OFFSET_LEDS: " + str(END_OFFSET_LEDS))

    CIRCUMFERENCE = DIAMETER_WLED * 3.14159265359
    SECTION_LENGTH = CIRCUMFERENCE / 20
    GAP_LEDS = 100 / LEDS_PER_METER
    LEDS_PER_SECTION = SECTION_LENGTH / GAP_LEDS
    AMOUNT_LEDS_CIRCLE_WITHOUT_OFFSET = int(LEDS_PER_SECTION * 20)
    AMOUNT_LEDS_CIRCLE = int(LEDS_PER_SECTION * 20 - END_OFFSET_LEDS)
    ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT = args['additional_leds_neighbour_segment']

    INNER_LEDS_PER_SECTION = {}
    OUTER_LEDS_PER_SECTION = {}

    if WLED_CIRLCES == 1 or WLED_SECOND_CIRCLE_DIRECTION == 1:
        END_OFFSET_LEDS = 0
        AMOUNT_LEDS_CIRCLE = AMOUNT_LEDS_CIRCLE_WITHOUT_OFFSET

    BOARD_NUMBERS_ORDER = [1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5, 20] \
        if WLED_MOUNT_CLOCKWISE == 1 else [20, 5, 12, 9, 14, 11, 8, 16, 7, 19, 3, 17, 2, 15, 10, 6, 13, 4, 18, 1]

    ##WLED_START_FACING == 1
    for i, seg_number in enumerate(BOARD_NUMBERS_ORDER):
        start_led = i * LEDS_PER_SECTION
        end_led = start_led + LEDS_PER_SECTION

        start_led_offset = (start_led - START_OFFSET_LEDS) % AMOUNT_LEDS_CIRCLE
        end_led_offset = (end_led - START_OFFSET_LEDS) % AMOUNT_LEDS_CIRCLE

        if start_led < START_OFFSET_LEDS:
            start_led_offset += END_OFFSET_LEDS

        if end_led < START_OFFSET_LEDS:
            end_led_offset += END_OFFSET_LEDS

        if start_led_offset < end_led_offset:
            if (start_led_offset - ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT) < 0:
                leds = list(range(int(start_led_offset), int(end_led_offset + ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT), AMOUNT_LEDS_CIRCLE))
            elif end_led_offset + ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT > AMOUNT_LEDS_CIRCLE:
                leds = list(range(int(start_led_offset - ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT), AMOUNT_LEDS_CIRCLE)) + list(range(0, int(end_led_offset + ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT)))
            else:
                leds = list(range(int(start_led_offset - ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT), min(int(end_led_offset + ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT), AMOUNT_LEDS_CIRCLE)))
        else:
            leds = list(range(int(start_led_offset - ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT), AMOUNT_LEDS_CIRCLE)) + list(range(0, int(end_led_offset + ADDITIONAL_LEDS_NEIGHBOUR_SEGMENT)))

        if WLED_START_FACING == 1:
            INNER_LEDS_PER_SECTION[seg_number] = leds
        elif WLED_START_FACING == 0:
            OUTER_LEDS_PER_SECTION[seg_number] = leds

    if WLED_CIRLCES > 1:
        ppi("WLED_SECOND_CIRCLE_DIRECTION: " + str(WLED_SECOND_CIRCLE_DIRECTION))

        for i, seg_number in enumerate(BOARD_NUMBERS_ORDER):
            if WLED_START_FACING == 1:
                if WLED_SECOND_CIRCLE_DIRECTION == 0:
                    OUTER_LEDS_PER_SECTION[seg_number] = [2 * AMOUNT_LEDS_CIRCLE_WITHOUT_OFFSET - led - 1
                                                          for led in INNER_LEDS_PER_SECTION[seg_number]]
                else:
                    OUTER_LEDS_PER_SECTION[seg_number] = [led + AMOUNT_LEDS_CIRCLE
                                                          for led in INNER_LEDS_PER_SECTION[seg_number]]
            elif WLED_START_FACING == 0:
                if WLED_SECOND_CIRCLE_DIRECTION == 0:
                    INNER_LEDS_PER_SECTION[seg_number] = [2 * AMOUNT_LEDS_CIRCLE_WITHOUT_OFFSET - led - 1
                                                          for led in OUTER_LEDS_PER_SECTION[seg_number]]
                else:
                    INNER_LEDS_PER_SECTION[seg_number] = [led + AMOUNT_LEDS_CIRCLE
                                                          for led in OUTER_LEDS_PER_SECTION[seg_number]]


    ppi("Circumference: " + str(CIRCUMFERENCE))
    ppi("Section Length: " + str(SECTION_LENGTH))
    ppi("Gap Leds: " + str(GAP_LEDS))
    ppi("Leds Per Section: " + str(LEDS_PER_SECTION))
    ppi("Amount Leds Circle: " + str(AMOUNT_LEDS_CIRCLE))
    ppi("Amount Leds Circle without offset: " + str(AMOUNT_LEDS_CIRCLE_WITHOUT_OFFSET))
    ppi("INNER_LEDS_PER_SECTION: " + str(INNER_LEDS_PER_SECTION))
    ppi("OUTER_LEDS_PER_SECTION: " + str(OUTER_LEDS_PER_SECTION))

    WLED_EFFECTS = list()
    try:
        effect_list_url = 'http://' + WLED_ENDPOINT_PRIMARY + WLED_EFFECT_LIST_PATH
        WLED_EFFECTS = requests.get(effect_list_url, headers={'Accept': 'application/json'})
        WLED_EFFECTS = [we.lower().split('@', 1)[0] for we in WLED_EFFECTS.json()]
        WLED_EFFECT_ID_LIST = list(range(0, len(WLED_EFFECTS) + 1))
        ppi("Your primary WLED-Endpoint (" + effect_list_url + ") offers " + str(len(WLED_EFFECTS)) + " effects")
    except Exception as e:
        ppe("Failed on receiving effect-list from WLED-Endpoint", e)
    
    BOARD_STOP_EFFECT = parse_effects_argument(args['board_stop_effect'])
    TAKEOUT_EFFECT = parse_effects_argument(args['takeout_effect'])
    CALIBRATION_EFFECT = parse_effects_argument(args['calibration_effect'])

    IDLE_EFFECT = parse_effects_argument(args['idle_effect'])
    GAME_WON_EFFECTS = parse_effects_argument(args['game_won_effects'])
    MATCH_WON_EFFECTS = parse_effects_argument(args['match_won_effects'])
    BUSTED_EFFECTS = parse_effects_argument(args['busted_effects'])
    HIGH_FINISH_EFFECTS = parse_effects_argument(args['high_finish_effects'])
    PLAYER_JOINED_EFFECTS = parse_effects_argument(args['player_joined_effects'])
    PLAYER_LEFT_EFFECTS = parse_effects_argument(args['player_left_effects'])

    SCORE_EFFECTS = dict()
    for v in range(0, 181):
        parsed_score = parse_effects_argument(args["score_" + str(v) + "_effects"])
        SCORE_EFFECTS[str(v)] = parsed_score
        # ppi(parsed_score)
        # ppi(SCORE_EFFECTS[str(v)])
    SCORE_AREA_EFFECTS = dict()
    for a in range(1, 13):
        parsed_score_area = parse_score_area_effects_argument(args["score_area_" + str(a) + "_effects"])
        SCORE_AREA_EFFECTS[a] = parsed_score_area
        # ppi(parsed_score_area)

    SEGMENT_HIT_EFFECTS = dict()
    for a in range(1, 21):
        parsed_segment = parse_segment_effects_argument(args["segment_" + str(a) + "_effects"], a)
        SEGMENT_HIT_EFFECTS[a] = parsed_segment
        # ppi(parsed_segment)
    SEGMENT_HIT_EFFECTS[25] = parse_segment_effects_argument(args["segment_25_effects"], 25)
    SEGMENT_HIT_EFFECTS[50] = parse_segment_effects_argument(args["segment_50_effects"], 50)

    # try:
    #     connect_data_feeder()
    #     for e in WLED_ENDPOINTS:
    #         connect_wled(e)
    #
    # except Exception as e:
    #     ppe("Connect failed: ", e)


time.sleep(5)
    



   
