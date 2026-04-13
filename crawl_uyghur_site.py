#!/usr/bin/env python3
"""Crawl a website and extract Uyghur text for corpus building.

No third-party dependencies are required.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
MULTISPACE_RE = re.compile(r"\s+")


@dataclass
class PageResult:
    url: str
    status: int | None
    error: str | None
    uyghur_lines: list[str]


class SimpleHTMLExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.text_chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "canvas", "iframe"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "canvas", "iframe"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data.strip():
            self.text_chunks.append(data)


def normalize_text(text: str) -> str:
    return MULTISPACE_RE.sub(" ", text).strip()


def contains_uyghur(text: str) -> bool:
    return bool(ARABIC_SCRIPT_RE.search(text))


def extract_from_html(html: str, base_url: str) -> tuple[list[str], list[str]]:
    parser = SimpleHTMLExtractor()
    parser.feed(html)

    lines: list[str] = []
    seen_text: set[str] = set()
    for raw in parser.text_chunks:
        txt = normalize_text(raw)
        if txt and contains_uyghur(txt) and txt not in seen_text:
            seen_text.add(txt)
            lines.append(txt)

    links: list[str] = []
    seen_links: set[str] = set()
    for href in parser.links:
        abs_url = urljoin(base_url, href)
        abs_url, _ = urldefrag(abs_url)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if abs_url in seen_links:
            continue
        seen_links.add(abs_url)
        links.append(abs_url)

    return lines, links


def same_domain(url: str, base_netloc: str) -> bool:
    return urlparse(url).netloc == base_netloc


def fetch_url(url: str, timeout: int, user_agent: str) -> tuple[int, str, str]:
    req = Request(url, headers={"User-Agent": user_agent})
    with urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", 200)
        content_type = resp.headers.get("Content-Type", "")
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        return status, content_type, text


def crawl(start_url: str, max_pages: int, delay: float, timeout: int, user_agent: str) -> list[PageResult]:
    parsed_start = urlparse(start_url)
    if parsed_start.scheme not in {"http", "https"}:
        raise ValueError("start-url must begin with http:// or https://")

    base_netloc = parsed_start.netloc
    q = deque([start_url])
    seen: set[str] = {start_url}
    results: list[PageResult] = []

    while q and len(results) < max_pages:
        url = q.popleft()
        try:
            status, content_type, html = fetch_url(url, timeout=timeout, user_agent=user_agent)
            if "text/html" not in content_type.lower():
                results.append(PageResult(url=url, status=status, error="non-html", uyghur_lines=[]))
                continue

            lines, links = extract_from_html(html, url)
            results.append(PageResult(url=url, status=status, error=None, uyghur_lines=lines))

            for link in links:
                if same_domain(link, base_netloc) and link not in seen:
                    seen.add(link)
                    q.append(link)
        except Exception as exc:  # noqa: BLE001
            results.append(PageResult(url=url, status=None, error=str(exc), uyghur_lines=[]))

        if delay > 0:
            time.sleep(delay)

    return results


def save_results(results: list[PageResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    pages_path = output_dir / "pages.jsonl"
    corpus_path = output_dir / "uyghur_corpus.txt"
    urls_path = output_dir / "crawled_urls.txt"

    total_lines = 0
    with pages_path.open("w", encoding="utf-8") as f_jsonl, corpus_path.open("w", encoding="utf-8") as f_txt, urls_path.open(
        "w", encoding="utf-8"
    ) as f_urls:
        for item in results:
            f_urls.write(item.url + "\n")
            f_jsonl.write(
                json.dumps(
                    {
                        "url": item.url,
                        "status": item.status,
                        "error": item.error,
                        "uyghur_lines": item.uyghur_lines,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            if item.uyghur_lines:
                f_txt.write(f"# URL: {item.url}\n")
                for line in item.uyghur_lines:
                    f_txt.write(line + "\n")
                    total_lines += 1
                f_txt.write("\n")

    summary = {
        "pages_total": len(results),
        "pages_with_uyghur": sum(1 for x in results if x.uyghur_lines),
        "uyghur_line_count": total_lines,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl a website and collect Uyghur text.")
    parser.add_argument("--start-url", required=True, help="Start URL, e.g. https://uyghur.xjass.cn/")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--max-pages", type=int, default=2000, help="Maximum pages to crawl")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay (seconds) between requests")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP request timeout in seconds")
    parser.add_argument(
        "--user-agent",
        default="UyghurCorpusCrawler/1.0 (+https://example.local)",
        help="HTTP User-Agent",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    results = crawl(
        start_url=args.start_url,
        max_pages=args.max_pages,
        delay=args.delay,
        timeout=args.timeout,
        user_agent=args.user_agent,
    )
    save_results(results, Path(args.output_dir))

    pages_with_uyghur = sum(1 for x in results if x.uyghur_lines)
    print(f"Done. Crawled pages: {len(results)}")
    print(f"Pages containing Uyghur text: {pages_with_uyghur}")
    print(f"Saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
