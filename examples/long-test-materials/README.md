# 长音频与复杂场景测试素材

本目录只保存测试素材的来源和下载清单，不保存大型数据集音频。请在下载前确认数据集许可证，并将下载后的文件放在本地目录：

```text
examples/long-test-materials/local/
```

`local/` 已被 `.gitignore` 忽略，不会被提交到公开 GitHub 仓库。

## 推荐顺序

### 1. AliMeeting：复杂长音频

- 来源：[OpenSLR SLR119 - AliMeeting](https://www.openslr.org/119/)
- 特点：中文多人会议，每个 session 约 15–30 分钟，通常包含 2–4 位说话人。
- 用途：验证长音频分段、多人切换、重叠语音、低置信度定位和错序处理。
- 许可证：CC BY-SA 4.0。
- 建议：先下载 dev 集或单个 session，不要下载完整训练集。

当前 MVP 不自动识别说话人，因此建议把它作为“复杂对轨压力测试”，而不是有声书角色标注的准确性测试。

### 2. WenetSpeech：有声书和戏剧场景

- 来源：[OpenSLR SLR121 - WenetSpeech](https://www.openslr.org/121/)
- 项目说明：[WenetSpeech GitHub](https://github.com/wenet-e2e/WenetSpeech)
- 特点：中文多领域语音，包含 audiobook、drama、news、interview 等场景。
- 用途：验证真实录音中的背景噪声、语速变化、角色切换和句子级时间定位。
- 许可证：CC BY 4.0。
- 建议：优先选择 audiobook 或 drama 子集，并保留对应 transcript 和原始 metadata。

WenetSpeech 的完整数据规模很大，下载入口可能需要填写信息或获取访问凭据；不要把凭据、完整数据或下载缓存提交到仓库。

### 3. LibriVox：版权友好的长篇旁白

- 来源：[LibriVox](https://librivox.org/?lang=en)
- 中文入口说明：[LibriVox 中文主页](https://wiki.librivox.org/index.php?title=Chinese_Homepage_Translation_%28Simplified%29)
- 特点：公版作品的章节级有声读物，适合长篇旁白和章节级对轨。
- 用途：验证长旁白、章节起止时间、文本与转写的连续匹配。
- 许可证：具体作品和录音请以 LibriVox 页面标注为准；不要默认所有转载页面都具有相同授权。
- 建议：选择同时能取得章节文本的作品，并在 `manifest.json` 中记录书名、章节、录音链接和文本链接。

### 4. MagicData Mandarin：干净的中文基线

- 来源：[OpenSLR SLR68 - MAGICDATA Mandarin Chinese Read Speech Corpus](https://www.openslr.org/68/)
- 特点：大规模中文朗读语音，提供分段文本和时间信息。
- 用途：验证中文归一化、漏读/错读/多读、短音频批量对轨和模型回归。
- 许可证：CC BY-NC-ND 4.0，仅适合符合许可证要求的测试用途。
- 建议：下载 dev/test 或少量样本，选取若干连续句段组成 5–10 分钟本地测试包。

## 用这些素材测试什么

| 素材 | 音频组织方式 | 主要验收点 |
| --- | --- | --- |
| AliMeeting | 一章长音频 | 长音频转写、重叠语音、低置信度、时间定位 |
| WenetSpeech audiobook/drama | 一章长音频 | 真实有声书场景、背景噪声、角色切换 |
| LibriVox | 一章长音频 | 公版旁白、连续片段匹配、章节级报告 |
| MagicData | 多段音频或拼接长音频 | 中文文本差异、批量对轨、回归测试 |

## 本地文件命名建议

```text
local/
├── alimeeting-session-01.wav
├── alimeeting-session-01.transcript.json
├── wenetspeech-drama-01.wav
├── wenetspeech-drama-01.transcript.json
├── librivox-chapter-01.mp3
├── librivox-chapter-01.txt
└── magicdata-dev-01.wav
```

对于长音频，上传到应用时选择“一章长音频”；对于 MagicData 的独立句段，选择“一段一音频”。

## 版权与仓库规则

- 不要把完整数据集、下载缓存或模型文件提交到公开仓库。
- 不要把数据集账号、访问凭据或 API Key 写入 `manifest.json`。
- 公开仓库只保留本说明和来源链接。
- 如果要把某个素材发布给第三方，先核对具体数据集和具体录音的许可证。
