import json
import logging
import sys

import requests


class TelegramClient:
    base_url = ''

    def __init__(self, disable_notification=False, chat_id='-1002155842956', **kwargs):
        super().__init__(**kwargs)
        self.token = '6712493300:AAGlNLpKiexRqrvMptvmtGma4yGTw0klkoc'
        self.disable_notification = disable_notification
        self.base_url = f'https://api.telegram.org/bot{self.token}/'

        # https://api.telegram.org/bot6712493300:AAGlNLpKiexRqrvMptvmtGma4yGTw0klkoc/getChat?chat_id=@tradebox_signal
        self.chat_id = chat_id

    def send_message(self, message):
        import re

        message = re.sub(r'[*]', '', message)

        response = requests.post(
            self.base_url + 'sendMessage',
            data={
                'chat_id': self.chat_id,
                'text': message,
                # 'parse_mode': 'markdown',
                'disable_notification': self.disable_notification,
                'disable_web_page_preview': True,
            }
        )

        if not response.json().get('ok'):
            logging.info(response.content)

            raise Exception('not ok, send to telegram')

        return response

