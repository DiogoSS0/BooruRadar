"""Aggregate endpoints used by the expanded catalog; no post objects are retained."""
from __future__ import annotations

import re
from html.parser import HTMLParser

import httpx

from booruradar.adapters.aggregate import AggregateAdapter, MoebooruAdapter, PhilomenaAdapter
from booruradar.adapters.base import AdapterResponseError
from booruradar.adapters.schemas import PublicStatistics
from booruradar.core.enums import AdapterFamily, MetricProvenance


class GelbooruXmlCounterAdapter(MoebooruAdapter):
    adapter_name = "gelbooru-xml-counter"
    family = AdapterFamily.GELBOORU
    statistics_path = "/index.php?page=dapi&s=post&q=index&limit=1"


class DanbooruCounterAdapter(AggregateAdapter):
    adapter_name = "danbooru-counter"
    family = AdapterFamily.DANBOORU
    statistics_path = "/counts/posts.json"
    total_posts_provenance = MetricProvenance.ESTIMATED

    def parse_count(self, response: httpx.Response) -> int:
        try:
            data = response.json()
        except ValueError as error:
            raise AdapterResponseError("counter was not valid JSON") from error
        if not isinstance(data, dict) or not isinstance(data.get("counts"), dict):
            raise AdapterResponseError("counts object is missing")
        value = data["counts"].get("posts")
        if type(value) is not int or data.get("capped") or data["counts"].get("capped"):
            raise AdapterResponseError("posts counter is missing, invalid or capped")
        return value


class ShuushuuAdapter(PhilomenaAdapter):
    adapter_name = "shuushuu"
    family = AdapterFamily.CUSTOM
    statistics_path = "/api/v1/images?per_page=1"


class UnfilteredPhilomenaAdapter(PhilomenaAdapter):
    """Check the actual filter configuration on every inspection, before counting."""
    adapter_name = "philomena-unfiltered"
    statistics_path = "/api/v1/json/search/images?q=*&per_page=1&filter_id=2"
    filter_path = "/api/v1/json/filters/2"

    async def fetch_public_statistics(self) -> PublicStatistics:
        if self._statistics is None:
            response = await self._get_counter_response(self.filter_path, "counter_filter")
            try:
                payload = response.json()
            except ValueError as error:
                raise AdapterResponseError("filter was not valid JSON") from error
            config = payload.get("filter") if isinstance(payload, dict) else None
            if not isinstance(config, dict) or type(config.get("id")) is not int or config["id"] != 2:
                raise AdapterResponseError("expected public filter is missing")
            if not (config.get("system") is True or config.get("public") is True):
                raise AdapterResponseError("counter filter is not publicly available")
            if (config.get("hidden_tag_ids") != [] or config.get("spoilered_tag_ids") != []
                    or "hidden_complex" not in config or config["hidden_complex"] not in (None, "")
                    or "spoilered_complex" not in config or config["spoilered_complex"] not in (None, "")):
                raise AdapterResponseError("counter filter is no longer unrestricted")
        return await super().fetch_public_statistics()


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


_INTEGER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"


class PhilomenaStatisticsAdapter(AggregateAdapter):
    """Site-wide net total, independent of search filters and deleted post IDs."""
    adapter_name = "philomena-statistics"
    family = AdapterFamily.PHILOMENA
    statistics_path = "/pages/stats"
    count_pattern = rf"(?<![\w.,+\-])({_INTEGER}) non-deleted images total in our database\."

    def parse_count(self, response: httpx.Response) -> int:
        parser = _VisibleTextParser()
        parser.feed(response.text)
        text = re.sub(r"\s+", " ", " ".join(parser.parts))
        counts = re.findall(self.count_pattern, text)
        if len(counts) != 1:
            raise AdapterResponseError("site-wide counter is missing or ambiguous")
        return int(counts[0].replace(",", ""))


class ShimmieHomeCounterAdapter(PhilomenaStatisticsAdapter):
    adapter_name = "shimmie-home-counter"
    family = AdapterFamily.SHIMMIE
    statistics_path = "/"
    count_pattern = rf"\bServing ({_INTEGER}) posts\b"


class _GelbooruDigitsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.digits: list[str] = []
        self.invalid = False
        self.groups = 0
        self.in_group = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        src = attributes.get("src") or ""
        if tag == "img" and src.startswith(("./counter/", "/counter/")):
            if not self.in_group:
                self.groups += 1
            self.in_group = True
            match = re.fullmatch(r"(?:\./|/)counter/([0-9])\.gif", src)
            digit = attributes.get("alt")
            if match is None or digit != match[1]:
                self.invalid = True
            else:
                self.digits.append(digit)
        else:
            self.in_group = False

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.in_group = False

    def handle_data(self, data):
        if data.strip():
            self.in_group = False


class GelbooruHomeCounterAdapter(AggregateAdapter):
    adapter_name = "gelbooru-home-counter"
    family = AdapterFamily.GELBOORU
    statistics_path = "/"

    def parse_count(self, response: httpx.Response) -> int:
        parser = _GelbooruDigitsParser()
        parser.feed(response.text)
        if parser.invalid or parser.groups != 1 or not 1 <= len(parser.digits) <= 18:
            raise AdapterResponseError("homepage counter is missing or ambiguous")
        return int("".join(parser.digits))
