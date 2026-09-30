# ADR-0060: 知识库与调研的文档格式扩展（docx / pptx / epub）

- 日期：2026-09-30（R-291）
- 状态：已接受
- 关联：ADR-0049（chunking v2）、ADR-0059（工具面扩展）、CONTEXT.md「Knowledge Base Index」

## 背景

用户 vault 为多种文件形式（笔记之外的 Word、PPT、电子书）。此前
`SUPPORTED_SUFFIXES` 只覆盖 md/txt/pdf/html，调研侧 fetch_extract 也
只接受文本类 content-type——Word/PPT/EPUB 在两条链路上都不可用。

## 决策

1. **单一格式抽取函数**：`kb.extract_text_from_bytes(data, suffix)`
   成为公共入口（txt/html/pdf/docx/pptx/epub 六格式），KB 索引器
   （`_extract_text(path)` 读盘委托）与 `web.fetch_extract`
   （HTTP bytes 委托）共用一份逻辑，杜绝两处分叉。
2. **vault 链路**：`SUPPORTED_SUFFIXES` 增补 `.docx/.pptx/.epub`——
   走既有通用切块（段落 1000/200 滑窗），无 md 专属增强（heading_path/
   tags/wikilinks 不适用）；增量更新按 mtime/size 对账照常生效。
   抽取形态：docx=段落+表格单元格（`row | ` 连接）；pptx=逐 slide
   文本框（`[Slide N]` 前缀）；epub=zip 内 xhtml 剥标签。
3. **调研链路**：fetch_extract 按 MIME（office/epub/pdf 映射）+ 
   octet-stream URL 后缀回退（对齐 download_pdf 的 R-31 规则）分流到
   同一抽取函数；抽不出文本报 permanent_error。
4. **新依赖**：python-docx、python-pptx（轻量纯解析）。
5. **明确不做**：旧版二进制 .doc（建议用户转 docx）；图片 OCR 与音频
   转写（成本/噪声比不成立，待真实痛点）。

## 后果

- vault 文字类内容全格式覆盖（笔记/文档/幻灯片/电子书），仅图片内容
  为有理由的空白（嵌入引用的 md 上下文本身已可检索）。
- 解析失败降级为空文本 + 警告日志，不阻塞 rebuild/调研。
- 抽取纯文本无样式信息（粗体/版式丢失），检索按纯文本语义进行。

## 演进注记

- 2026-09-30（R-291）：初版落地。
