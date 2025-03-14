import os
import socks
import shutil
import random
import time
import httpx
import json
import re
import asyncio
from telethon import TelegramClient,functions
from telethon.tl.types import MessageMediaPhoto
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
'''
代理参数说明:
# SOCKS5
proxy = (socks.SOCKS5,proxy_address,proxy_port,proxy_username,proxy_password)
# HTTP
proxy = (socks.HTTP,proxy_address,proxy_port,proxy_username,proxy_password))
# HTTP_PROXY
proxy=(socks.HTTP,http_proxy_list[1][2:],int(http_proxy_list[2]),proxy_username,proxy_password)
'''

if os.environ.get("HTTP_PROXY"):
    http_proxy_list = os.environ["HTTP_PROXY"].split(":")


class TGForwarder:
    def __init__(self, api_id, api_hash, string_session, channels_to_monitor, groups_to_monitor, forward_to_channel,
                 limit, replies_limit, kw, ban, only_send, nokwforwards, fdown, download_folder, proxy, checknum, linkvalidtor):
        self.checkbox = {}
        self.checknum = checknum
        self.history = 'history.json'
        # 正则表达式匹配资源链接
        self.pattern = r"(?:链接：\s*)?(https?://[^\s]+|magnet:.+)"
        self.api_id = api_id
        self.api_hash = api_hash
        self.string_session = string_session
        self.channels_to_monitor = channels_to_monitor
        self.groups_to_monitor = groups_to_monitor
        self.forward_to_channel = forward_to_channel
        self.limit = limit
        self.replies_limit = replies_limit
        self.kw = kw
        self.ban = ban
        self.linkvalidtor = linkvalidtor
        self.only_send = only_send
        self.nokwforwards = nokwforwards
        self.fdown = fdown
        self.download_folder = download_folder
        if not proxy:
            self.client = TelegramClient(StringSession(string_session), api_id, api_hash)
        else:
            self.client = TelegramClient(StringSession(string_session), api_id, api_hash, proxy=proxy)

    def random_wait(self, min_ms, max_ms):
        min_sec = min_ms / 1000
        max_sec = max_ms / 5000
        wait_time = random.uniform(min_sec, max_sec)
        time.sleep(wait_time)

    def contains(self, s, kw):
        return any(k in s for k in kw)

    def nocontains(self, s, ban):
        return not any(k in s for k in ban)

    async def send(self, message, target_chat_name):
        if self.fdown and message.media and isinstance(message.media, MessageMediaPhoto):
            media = await message.download_media(self.download_folder)
            await self.client.send_file(target_chat_name, media, caption=message.message)
        else:
            await self.client.send_message(target_chat_name, message.message)

    async def get_peer(self,client, channel_name):
        peer = None
        try:
            peer = await client.get_input_entity(channel_name)
        except Exception as e:
            print(f"Unexpected error: {e}")
        finally:
            return peer

    async def get_all_replies(self,chat_name, message):
        '''
        获取频道消息下的评论，有些视频/资源链接被放在评论中
        '''
        offset_id = 0
        all_replies = []
        peer = await self.get_peer(self.client, chat_name)
        if peer is None:
            return []
        while True:
            try:
                replies = await self.client(functions.messages.GetRepliesRequest(
                    peer=peer,
                    msg_id=message.id,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=100,
                    max_id=0,
                    min_id=0,
                    hash=0
                ))
                all_replies.extend(replies.messages)
                if len(replies.messages) < 100:
                    break
                offset_id = replies.messages[-1].id
            except Exception as e:
                print(f"Unexpected error while fetching replies: {e.__class__.__name__} {e}")
                break
        return all_replies
    async def forward_messages(self, chat_name, target_chat_name):
        global total
        links = self.checkbox['links']
        sizes = self.checkbox['sizes']
        try:
            if try_join:
                await self.client(JoinChannelRequest(chat_name))
            chat = await self.client.get_entity(chat_name)
            messages = self.client.iter_messages(chat, limit=self.limit)
            async for message in messages:
                self.random_wait(200, 1000)
                forwards = message.forwards
                if message.media:
                    # 视频
                    if hasattr(message.document, 'mime_type') and self.contains(message.document.mime_type,'video') and self.nocontains(message.message, self.ban):
                        if forwards:
                            size = message.document.size
                            if size not in sizes:
                                await self.client.forward_messages(target_chat_name, message)
                                sizes.append(size)
                                total += 1
                            else:
                                print(f'视频已经存在，size: {size}')
                    # 图文(匹配关键词)
                    elif self.contains(message.message, self.kw) and message.message and self.nocontains(message.message, self.ban):
                        matches = re.findall(self.pattern, message.message)
                        if matches:
                            link = matches[0]
                            if link not in links:
                                link_ok = True if not self.linkvalidtor else False
                                if self.linkvalidtor:
                                    result = await self.netdisklinkvalidator(matches)
                                    for r in result:
                                        if r[1]:
                                            link_ok = True
                                if forwards and not self.only_send and link_ok:
                                    await self.client.forward_messages(target_chat_name, message)
                                    total += 1
                                    links.append(link)
                                elif link_ok:
                                    await self.send(message, target_chat_name)
                                    total += 1
                                    links.append(link)
                            else:
                                print(f'链接已存在，link: {link}')
                    # 图文(不含关键词，默认nokwforwards=False)，资源被放到评论中
                    elif self.nokwforwards and message.message and self.nocontains(message.message, self.ban):
                        replies = await self.get_all_replies(chat_name,message)
                        replies = replies[-self.replies_limit:]
                        for r in replies:
                            # 评论中的视频
                            if hasattr(r.document, 'mime_type') and self.contains(r.document.mime_type,'video') and self.nocontains(r.message, self.ban):
                                size = r.document.size
                                if size not in sizes:
                                    await self.client.forward_messages(target_chat_name, r)
                                    total += 1
                                    sizes.append(size)
                                else:
                                    print(f'视频已经存在，size: {size}')
                            # 评论中链接关键词
                            elif self.contains(r.message, self.kw) and r.message and self.nocontains(r.message, self.ban):
                                matches = re.findall(self.pattern, r.message)
                                if matches:
                                    link = matches[0]
                                    if link not in links:
                                        link_ok = True if not self.linkvalidtor else False
                                        if self.linkvalidtor:
                                            result = await self.netdisklinkvalidator(matches)
                                            for r in result:
                                                if r[1]:
                                                    link_ok = r[1]
                                        if forwards and not self.only_send and link_ok:
                                            await self.client.forward_messages(target_chat_name, r)
                                            total += 1
                                            links.append(link)
                                        elif link_ok:
                                            await self.send(r, target_chat_name)
                                            total += 1
                                            links.append(link)
                                    else:
                                        print(f'链接已存在，link: {link}')

            self.checkbox['links'] = links
            self.checkbox['sizes'] = sizes
            print(f"从 {chat_name} 转发资源到 {self.forward_to_channel} total: {total}")
        except Exception as e:
            print(f"从 {chat_name} 转发资源到 {self.forward_to_channel} 失败: {e}")
    async def checkhistory(self):
        '''
        检索历史消息用于过滤去重
        '''
        # post_ids = []
        links = []
        sizes = []
        if os.path.exists(self.history):
            with open(self.history, 'r', encoding='utf-8') as f:
                self.checkbox = json.loads(f.read())
                links = self.checkbox.get('links')
                sizes = self.checkbox.get('sizes')
        else:
            self.checknum = 5000

        chat = await self.client.get_entity(self.forward_to_channel)
        messages = self.client.iter_messages(chat, limit=self.checknum)
        async for message in messages:
            # print(f'{self.forward_to_channel}: {message.id}')
            # 视频类型对比大小
            if hasattr(message.document, 'mime_type'):
                sizes.append(message.document.size)
            # 匹配出链接
            if message.message:
                matches = re.findall(self.pattern, message.message)
                for match in matches:
                    links.append(match)
            # 消息类型为转发-不再从相同频道再次转发，links可以覆盖该场景
            # if message.fwd_from:
            #     post_ids.append(f'{message.fwd_from.from_id.channel_id}_{message.fwd_from.channel_post}')
        # self.checkbox['posts_ids']=list(set(post_ids))
        self.checkbox['links'] = list(set(links))
        self.checkbox['sizes'] = list(set(sizes))
    async def check_aliyun(self,share_id):
        api_url = "https://api.aliyundrive.com/adrive/v3/share_link/get_share_by_anonymous"
        headers = {"Content-Type": "application/json"}
        data = json.dumps({"share_id": share_id})
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, headers=headers, data=data)
            response_json = response.json()
            if response_json.get('has_pwd'):
                return True
            if response_json.get('code') == 'NotFound.ShareLink':
                return False
            if not response_json.get('file_infos'):
                return False
            return True
    async def check_115(self,share_id):
        api_url = "https://webapi.115.com/share/snap"
        params = {"share_code": share_id, "receive_code": ""}
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, params=params)
            response_json = response.json()
            if response_json.get('state'):
                return True
            elif '请输入访问码' in response_json.get('error', ''):
                return True
            return False
    async def check_quark(self,share_id):
        api_url = "https://drive.quark.cn/1/clouddrive/share/sharepage/token"
        headers = {"Content-Type": "application/json"}
        data = json.dumps({"pwd_id": share_id, "passcode": ""})
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, headers=headers, data=data)
            response_json = response.json()
            if response_json.get('message') == "ok":
                token = response_json.get('data', {}).get('stoken')
                if not token:
                    return False
                detail_url = f"https://drive-h.quark.cn/1/clouddrive/share/sharepage/detail?pwd_id={share_id}&stoken={token}&_fetch_share=1"
                detail_response = await client.get(detail_url)
                detail_response_json = detail_response.json()
                if detail_response_json.get('data', {}).get('share', {}).get('status') == 1:
                    return True
                else:
                    return False
            elif response_json.get('message') == "需要提取码":
                return True
            return False
    def extract_share_id(self,url):
        if "aliyundrive.com" in url or "alipan.com" in url:
            pattern = r"https?://[^\s]+/s/([a-zA-Z0-9]+)"
        elif "pan.quark.cn" in url:
            pattern = r"https?://[^\s]+/s/([a-zA-Z0-9]+)"
        elif "115.com" in url:
            pattern = r"https?://[^\s]+/s/([a-zA-Z0-9]+)"
        elif url.startswith("magnet:"):
            return "magnet"  # 磁力链接特殊值
        else:
            return None
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        return None
    async def check_url(self,url):
        share_id = self.extract_share_id(url)
        if not share_id:
            print(f"无法识别的链接或网盘服务: {url}")
            return url, False
        if "aliyundrive.com" in url or "alipan.com" in url:
            result = await self.check_aliyun(share_id)
            return url, result
        elif "pan.quark.cn" in url:
            result = await self.check_quark(share_id)
            return url, result
        elif "115.com" in url:
            result = await self.check_115(share_id)
            return url, result
        elif share_id == "magnet":
            return url, True  # 磁力链接直接返回True
    async def netdisklinkvalidator(self,urls):
        tasks = [self.check_url(url) for url in urls]
        results = await asyncio.gather(*tasks)
        for url, result in results:
            print(f"{url} - {'有效' if result else '无效'}")
        return results
    async def main(self):
        await self.checkhistory()
        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)
        for chat_name in self.channels_to_monitor + self.groups_to_monitor:
            global total
            total = 0
            await self.forward_messages(chat_name, self.forward_to_channel)
        await self.client.disconnect()
        if self.fdown:
            shutil.rmtree(self.download_folder)

        with open(self.history,'w+',encoding='utf-8') as f:
            f.write(json.dumps(self.checkbox))

    def run(self):
        with self.client.start():
            self.client.loop.run_until_complete(self.main())


if __name__ == '__main__':
    channels_to_monitor = ['DSJ1314', 'guaguale115', 'hao115', 'shareAliyun', 'alyp_JLP', 'Quark_Share_Channel']
    groups_to_monitor = []
    forward_to_channel = 'wjjxqx'
    # 监控最近消息数
    limit = 30
    # 监控消息中评论数，有些视频、资源链接被放到评论中
    replies_limit = 1
    kw = ['链接', '片名', '名称', '剧名','pan.quark.cn','115.com','alipan.com','aliyundrive.com']
    ban = ['预告', '预感', 'https://t.me/', '盈利', '即可观看', '书籍', '电子书', '图书', '软件', '安卓', '风水', '教程', '课程', 'Android']
    # 尝试加入公共群组频道，无法过验证
    try_join = False
    # 消息中不含关键词图文，但有些资源被放到消息评论中，如果需要监控评论中资源，需要开启，否则建议关闭
    nokwforwards = True
    # 图文资源只主动发送，不转发，可以降低限制风险；不支持视频场景
    only_send = True
    # 当频道禁止转发时，是否下载图片发送消息
    fdown = True
    download_folder = 'downloads'
    api_id = 20017392
    api_hash = '116acb9fe95f1ea94b5af71d583aed3c'
    string_session = '1BVtsOHsBu1GKzpS7h2uNKkbhGijLLgC-YKIAxoLeGaS33E8FfVOaOROwZ-rfvQ9fruCF2r0rGBuxKkc4tFfGTmvZn8lcb1zuVjcKRGFxwyudaWWsZQpddBtEcBozHo2596tPqJIAShqNpX6wiRFz8aHQMJJhtentomJ6OUZ1-CAKKYSBkcSn6oiTGXc9e193UlOnmBryxbXk4vzLOt2rRgWmcr9-bYMebRXol_tY0h_Jdk2Mf09zmxNTGACVyLNod_fc_7DnHDIwuwyZkdrd2f1KVWjZ9qDf4j_XQ3N3-IjI4iyUWjWtm0oNInmRKwuUWm5D6qqYEBI0lEJeEdIJSFq9vVZODE8='
    # 默认不开启代理
    proxy = None
    # 检测自己频道最近 500 条消息是否已经包含该资源
    checknum = 500
    # 对网盘链接有效性检测
    linkvalidtor = False
    forwarder = TGForwarder(api_id, api_hash, string_session, channels_to_monitor, groups_to_monitor, forward_to_channel, limit, replies_limit, kw,
                             ban, only_send, nokwforwards, fdown, download_folder, proxy, checknum, linkvalidtor)
    forwarder.run()
