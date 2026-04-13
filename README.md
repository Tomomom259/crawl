# Uyghur 语料抓取脚本

这个仓库提供一个可直接运行的脚本：从指定站点开始，抓取**同域名**链接，并提取页面中的维吾尔文（阿拉伯字母区段）文本，适合作为后续预训练的原始语料准备步骤。

## 环境

- Python 3.9+
- 无第三方依赖（仅使用标准库）

## 使用方式

```bash
python crawl_uyghur_site.py \
  --start-url https://uyghur.xjass.cn/ \
  --output-dir output_uyghur \
  --max-pages 5000 \
  --delay 0.3
```

## 输出文件

- `pages.jsonl`: 每个页面一行（URL、HTTP 状态、错误信息、提取到的维吾尔文本列表）
- `uyghur_corpus.txt`: 聚合后的纯文本语料（按 URL 分块）
- `crawled_urls.txt`: 已访问 URL 列表
- `summary.json`: 统计摘要

## 注意事项

1. 先确认目标网站的 robots 协议与使用条款，确保抓取行为合规。
2. 建议设置合理 `--delay`，避免对站点造成过大压力。
3. 本脚本默认只抓取与起始 URL 同域名的页面。
