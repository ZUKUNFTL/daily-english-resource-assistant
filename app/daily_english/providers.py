from __future__ import annotations

from abc import ABC, abstractmethod
from html import unescape
from urllib.parse import quote_plus

import requests

from .models import Resource


class ResourceProvider(ABC):
    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[Resource]: ...


class TedProvider(ResourceProvider):
    API_URL = "https://www.ted.com/search"

    def search(self, query: str, limit: int = 10) -> list[Resource]:
        response = requests.get(
            self.API_URL, params={"q": query, "sort": "relevance"},
            timeout=15, headers={"User-Agent": "DailyEnglishAssistant/0.1"},
        )
        response.raise_for_status()
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.text, "html.parser")
        resources: list[Resource] = []
        for anchor in soup.select('a[href*="/talks/"]'):
            href = anchor.get("href", "")
            title = " ".join(anchor.stripped_strings)
            if not title or href.count("/") < 2:
                continue
            url = href if href.startswith("http") else f"https://www.ted.com{href.split('?')[0]}"
            if any(item.url == url for item in resources):
                continue
            resources.append(Resource(
                provider="TED", title=unescape(title), url=url,
                captions="请在 TED 页面确认语言字幕", license_note="仅打开 TED 官方页面；媒体请按 TED 条款使用。",
            ))
            if len(resources) >= limit:
                break
        return resources


class YouTubeProvider(ResourceProvider):
    API_URL = "https://www.googleapis.com/youtube/v3/search"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key.strip()

    def search(self, query: str, limit: int = 10) -> list[Resource]:
        if not self.api_key:
            raise ValueError("请先在设置中填写个人 YouTube Data API Key")
        response = requests.get(
            self.API_URL,
            params={
                "key": self.api_key, "part": "snippet", "q": query, "type": "video",
                "maxResults": min(max(limit, 1), 50), "relevanceLanguage": "en",
            },
            timeout=15,
        )
        if response.status_code in {400, 403}:
            detail = response.json().get("error", {}).get("message", "API Key 无效或配额不足")
            raise ValueError(f"YouTube 搜索失败：{detail}")
        response.raise_for_status()
        resources = []
        for item in response.json().get("items", []):
            snippet = item["snippet"]
            video_id = item["id"]["videoId"]
            resources.append(Resource(
                provider="YouTube", title=snippet["title"], author=snippet["channelTitle"],
                url=f"https://www.youtube.com/watch?v={video_id}", captions="请在 YouTube 页面确认字幕",
                license_note="只提供公开链接；请确认授权后自行导入本地媒体。",
                download_url=f"https://www.youtube.com/watch?v={video_id}",
            ))
        return resources


class BilibiliProvider(ResourceProvider):
    API_URL = "https://api.bilibili.com/x/web-interface/search/type"

    def search(self, query: str, limit: int = 10) -> list[Resource]:
        response = requests.get(
            self.API_URL,
            params={"search_type": "video", "keyword": query, "page_size": min(max(limit, 1), 50)},
            headers={"User-Agent": "DailyEnglishAssistant/0.1", "Referer": "https://www.bilibili.com/"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in {0, None}:
            raise ValueError(f"B 站搜索失败：{payload.get('message', payload.get('code'))}")
        from bs4 import BeautifulSoup

        resources = []
        for item in (payload.get("data", {}).get("result") or [])[:limit]:
            title = BeautifulSoup(item.get("title", ""), "html.parser").get_text(" ", strip=True)
            bvid = item.get("bvid") or item.get("arcurl", "").rstrip("/").split("/")[-1]
            if not bvid:
                continue
            url = f"https://www.bilibili.com/video/{bvid}"
            resources.append(Resource(
                provider="Bilibili", title=title, author=item.get("author", ""), url=url,
                language="中文", captions="请在 B 站页面确认字幕",
                license_note="只提供公开链接；请确认授权后自行导入本地媒体。", download_url=url,
            ))
        return resources


def browser_search_url(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"


def bilibili_search_url(query: str) -> str:
    return f"https://search.bilibili.com/all?keyword={quote_plus(query)}"
