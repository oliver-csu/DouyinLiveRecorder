import _thread
import gzip
import time
import traceback

import websocket
from google.protobuf import json_format

from dylr.core import dy_api, app, record_manager
from dylr.core.dy_protocol import PushFrame, Response, ChatMessage
from dylr.util import logger, cookie_utils


class DanmuRecorder:
    def __init__(self, room, room_real_id, start_time=None):
        self.room = room
        self.room_id = room.room_id
        self.room_name = room.room_name
        self.room_real_id = room_real_id
        self.start_time = start_time
        self.ws = None
        self.stop_signal = False
        self.danmu_amount = 0
        self.last_danmu_time = 0
        self.retry = 0

    def start(self):
        if self.start_time is None:
            self.start_time = time.localtime()
        self.start_time_t = int(time.mktime(self.start_time))
        logger.info_and_print(f'开始录制 {self.room_name}({self.room_id}) 的弹幕')

        self.ws = websocket.WebSocketApp(
            url=dy_api.get_danmu_ws_url(self.room_id, self.room_real_id),
            header=dy_api.get_request_headers(), cookie=cookie_utils.cookie_cache,
            on_message=self._onMessage, on_error=self._onError, on_close=self._onClose,
            on_open=self._onOpen,
        )
        self.ws.run_forever()

    def stop(self):
        self.stop_signal = True

    def _onOpen(self, ws):
        _thread.start_new_thread(self._heartbeat, (ws,))

    def _onMessage(self, ws: websocket.WebSocketApp, message: bytes):
        wssPackage = PushFrame()
        wssPackage.ParseFromString(message)
        logid = wssPackage.logid
        decompressed = gzip.decompress(wssPackage.payload)
        payloadPackage = Response()
        payloadPackage.ParseFromString(decompressed)

        # 发送ack包
        if payloadPackage.needAck:
            obj = PushFrame()
            obj.payloadType = 'ack'
            obj.logid = logid
            obj.payloadType = payloadPackage.internalExt
            data = obj.SerializeToString()
            ws.send(data, websocket.ABNF.OPCODE_BINARY)
        # 处理消息
        for msg in payloadPackage.messagesList:
            if msg.method == 'WebcastChatMessage':
                chatMessage = ChatMessage()
                chatMessage.ParseFromString(msg.payload)
                data = json_format.MessageToDict(chatMessage, preserving_proto_field_name=True)
                now = time.time()
                second = now - self.start_time_t
                self.danmu_amount += 1
                self.last_danmu_time = now
                user = data['user']['nickName']
                content = data['content']

    def _heartbeat(self, ws: websocket.WebSocketApp):
        t = 9
        while True:
            if app.stop_all_threads or self.stop_signal:
                ws.close()
                break
            if not ws.keep_running:
                break
            if t % 10 == 0:
                obj = PushFrame()
                obj.payloadType = 'hb'
                data = obj.SerializeToString()
                ws.send(data, websocket.ABNF.OPCODE_BINARY)
                # 没弹幕，重新连接
                if self.retry < 3 and self.danmu_amount == 0 and t > 30:
                    ws.close()
                    logger.warning_and_print(f'{self.room_name}({self.room_id}) 无法获取弹幕，正在重试({self.retry+1})')
                    # time.sleep(5)
                    # if dy_api.is_going_on_live(self.room):
                    #     self.start_time = None  # 防止同名覆盖
                    #     self.start()
                    #     self.retry += 1
                    #     break
                now = time.time()
                # 太长时间没弹幕，检测是否是下播了，可能下播后并没有断开 websocket
                if t > 30 and now - self.last_danmu_time > 60:
                    if not dy_api.is_going_on_live(self.room):
                        ws.close()
            t += 1
            time.sleep(1)

    def _onError(self, ws, error):
        logger.error_and_print(f'[onError] {self.room_name}({self.room_id})弹幕录制抛出一个异常')
        logger.error_and_print(traceback.format_exc())


    def _onClose(self, ws, a, b):
        logger.info_and_print(f'{self.room_name}({self.room_id}) 弹幕录制结束')
        if app.stop_all_threads:
            return
        if self.retry < 10 and dy_api.is_going_on_live(self.room):
            self.retry += 1
            logger.info_and_print(f'{self.room_name}({self.room_id})弹幕录制重试({self.retry})')
            self.start_time = None
            time.sleep(1)
            self.start()
