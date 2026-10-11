# AlphaTech API Suno 协议记录

生产环境的 NewAPI Suno 路由是：

- 当前渠道：ID `10`，名称 `Suno-AI`，类型 `36`（SunoAPI），上游 Base URL 为
  `https://aipaiai.cn`，启用模型为 `suno_music` 和 `suno_lyrics`。
- Skill 只访问 AlphaTech 的公开 API 地址，并携带 AlphaTech 用户 Bearer token；
  不要把 `https://aipaiai.cn` 当作客户端 Base URL，也不要把渠道 key 发给上游。

- `POST /suno/submit/MUSIC`
- `POST /suno/submit/LYRICS`
- `POST /suno/fetch`，请求体为 `{"ids":["task_xxx"]}`
- `GET /suno/fetch/:id`

提交成功时 NewAPI 返回类似 `{"code":"success","data":"task_xxx"}`，其中
`task_xxx` 是对用户公开的任务 ID。轮询结果是任务 DTO，`data` 字段包含上游
Suno 的结果数据；常见歌曲字段为 `audio_url`、`video_url`、`image_url`、
`image_large_url`、`title`、`text` 和 `status`。

`code` 以字符串 `success` 为主；兼容部署也可能返回数字 `200` 或 `0`。成功响应
必须包含 `data`，否则应视为协议错误。`/suno/fetch` 的 `data` 是任务 DTO 数组，
每项至少包含 `task_id`、`status`、`fail_reason`、时间戳和可选的嵌套 `data`。
任务状态通常为 `submitted`、`queueing`、`processing`、`success` 或 `failed`；
Skill 只在终态后停止轮询，超时不应重新提交原任务。

`MUSIC` 请求支持 `prompt`、`title`、`tags`、`mv`、`make_instrumental`、
`continue_at`、`continue_clip_id` 和 `gpt_description_prompt`。NewAPI 在
未提供 `mv` 时默认使用 `chirp-v3-0`。`LYRICS` 至少需要非空 `prompt`。

鉴权使用 AlphaTech API 用户 Bearer token，不使用 Suno 渠道的上游 key。渠道
key 只保存在服务器端，Skill 不应读取、打印或覆盖它。
