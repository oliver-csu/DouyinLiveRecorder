import os

import requests
from requests.adapters import HTTPAdapter

from dylr.plugin import plugin
from dylr.core import app, config, transcode_manager
from dylr.core.room import Room
from dylr.core.room_info import RoomInfo
from dylr.util import cookie_utils, logger


class VideoRecorder:
    def __init__(self, room: Room, room_info: RoomInfo, recording):
        self.room = room
        self.room_info = room_info
        self.stop_signal = False
        self.recording = recording

    def stop(self):
        self.stop_signal = True

    def start_recording(self, filename: str):
        stream_url = self.room_info.get_stream_url()
        if stream_url is None:
            logger.error_and_print(f'{self.room.room_name}({self.room.room_id}) 获取直播资源链接失败')
            cookie_utils.record_cookie_failed()
            return

        # 获取成功，清除 cookie failed 记录
        cookie_utils.cookie_failed = 0

        s = requests.Session()
        s.mount(stream_url, HTTPAdapter(max_retries=3))
        for retry in range(1, 5):
            if retry == 4:
                logger.error_and_print(f'{self.room.room_name}({self.room.room_id})直播获取超时。')
                self.stop()
                return
            try:
                downloading = s.get(
                    stream_url, timeout=(5, 10), verify=False, stream=True
                )
                break
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                logger.error_and_print(f'{self.room.room_name}({self.room.room_id})直播获取超时，正在重试({retry})')


        try:
            for data in downloading.iter_content(chunk_size=1024):
                if data:
                    # file.write(data)
                    if self.stop_signal:  # 主动停止录制
                        logger.info_and_print(f'主动停止{self.room.room_name}({self.room.room_id})的录制')
                        break
        except requests.exceptions.ConnectionError:
            # 下载出错(一般是下载超时)，可能是直播已结束，或主播长时间卡顿，先结束录制，然后再检测是否在直播
            pass
        # 结束录制
        logger.info_and_print(f'{self.room.room_name}({self.room.room_id}) 录制结束')
        plugin.on_live_end(self.room, filename)

        # 自动转码
        if config.is_auto_transcode():
            transcode_manager.start_transcode(filename)

        # 再次检测是否在直播，防止因网络问题造成的提前停止录制
        # 如果是主动停止录制，则不立刻再次检查
        if not self.stop_signal:
            self.recording.refresh_video_recorder()
        self.stop()
