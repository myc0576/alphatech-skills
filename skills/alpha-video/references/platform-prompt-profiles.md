# 多平台 Prompt 画像与编译规则

平台能力会变化。生产时先读取机器可读的 [`platform-profiles.json`](platform-profiles.json)，按 `aliases` 解析平台；需要更新易变事实时查官方来源并同步 `verified_at`。官方能力写在 `capabilities`，Skill 的保守执行预算写在 `compiler_policy`，两者不得混写。

## 共用路由

1. 平台已知：解析平台画像，检查时长、画幅和输入模式，再选择平台 Prompt 结构。
2. 平台名称无法匹配：使用 `generic`，保留 `requested_name`，不猜测负面词栏、参考数量、首尾帧或声音能力。
3. 先把 A 稿转成动作状态中间层，再运行 `scripts/prompt_compiler.py audit`；有硬错误不得交付为最终 B 稿。
4. 完整项目 B 稿只出现一次全局高燃固定块。拆镜 Prompt 只执行当前 beat 分配的主运镜、动作、接触、反馈和结束状态，不复制整套摄影词。
5. 编译策略不是平台保证。平台官方文档声称支持复杂动作或多主体，也不等于任意高负载镜头能稳定实现。只有带 `role/priority/causal_binding` 的结构化 VFX 超预算时才可确定性裁减并记录；主体/微动作或无结构 VFX 超预算会作为硬错误返回，要求重写，禁止机械截断角色、动作因果或关键接触反馈。

## Seedance 2.0

- 适合：15 秒多镜叙事、图/视频/音频混合参考、动作或镜头参考、视频延长和编辑。
- 编译：角色/武器/场景参考先做职责解耦；时间轴可以多镜，但每镜保持一条主攻防因果和一个主运镜；多人合击用状态接力，不同时启动多套完整技能。
- 降负：先删装饰与背景独立事件，再减并发 VFX 和复杂环绕；仍过载时按自然动作转折拆镜。
- 边界：官方确认的最长时长为 15 秒；负面提示词栏、首尾帧入口等未在当前来源明确确认时保持未知。

## Seedance 2.5

- 适合：最长 30 秒的长叙事、多轮延长、大容量多模态参考、跨镜人物/场景连续与时间戳级编辑。
- 编译：先读取 [seedance-2.5-prompt-engineering.md](seedance-2.5-prompt-engineering.md)，建立 `reference_role_manifest`，显式标注 `@Image/@Video/@Audio` 的唯一职责；同一实体的多角度参考必须用 `entity` 分组归一化，不继承各参考的隐含背景或姿势。
- Prompt 结构：按 `format → subject → action → environment → camera → look → timing → audio_and_constraints` 组织全片简报；30 秒按 4–6 个功能段编排，每段只保留一个主动作、一个主运镜、一个结果和可继承结束状态。
- 时间轴：用累计时间段从 `00` 连续覆盖到项目结尾；动作后的余势、呼吸、环境响应和收束写在同一段或显式延续段，不留未定义空档。编译器会在 beat 总时长不足时生成“最后状态延续”尾段并在审计中提示。
- 音频：对白、接触音效、环境声和音乐分层；对白只使用用户提供或确认的原句。音效确认可见接触，不能替代命中或受力。
- 局部编辑：使用 `edit_plan.mode=timestamp_edit`，同时声明 `source/keep/changes`；未列出的时间段保留原视频的身份、动作、灯光、音频和连续性。
- 30 秒高燃战斗优先分成 4–6 个功能段，每段仍遵守单主动作、单主运镜和明确结束状态；高潮前必须有优势变化或代价。
- 边界：截至 2026-09-08，官方资料说明在即梦与豆包 Pro 上线，BytePlus ModelArk API 仍以当前文档为准；API 字段不得提前编造。证据来源见 [platform-profiles.json](platform-profiles.json) 与 [seedance-2.5-prompt-engineering.md](seedance-2.5-prompt-engineering.md)。

## HappyHorse 1.0

- 适合：当前网页端公开的 4–15 秒文生视频、图生视频。
- 编译：短句、单主语、单环境、单动作目的、单主运镜、可见结果；参考图存在时让图片承担外观和场景，文本不要重复堆外观细节。
- 高速打斗默认比 Seedance/H3 更保守：每 beat 最多 2 个活动主体、3 个微动作和 1 套主要 VFX；复杂团队战优先拆镜。
- 当前编译工作流只启用 `input_mode=text`（不带参考文件）和 `input_mode=image`（1–9 张图、无视频/音频）。文档所述最多 3 视频、3 音频和混合 12 文件保存在画像的 `documented_but_not_enabled`，编译器不消费；不能通过给 text 模式附加视频/音频绕过入口边界。
- 边界：文档描述模型具备更广多模态能力，但当前网页端公开入口与完整模型能力不是同一概念；未确认功能保持 `unknown`，取得可验证入口后再新增独立 workflow。

## MiniMax H3

- 适合：4–15 秒、多画幅、原生音视频、首帧/尾帧/首尾帧控制和全模态参考。
- 编译：优先使用 `integrated_multimodal_description` 与 `[Shot N]`；逐镜写主体、动作状态、摄影触发和结果，声音使用 `overall_soundscape`，素材关系写清“哪个输入负责什么”。
- FL2VA：一张图时明确是首帧还是尾帧；两张图时检查起止人物、武器、姿态、方向和场景状态可达。
- Ref2VA：参考视频负责动作/运镜时，不继承其中人物身份；人物图负责身份时，不继承姿势和背景。
- 项目 JSON 使用 `input_mode=text / first_frame / last_frame / first_last_frame / reference` 区分工作流。FL2VA 的图像数分别为 0/1/1/2 且不带视频或音频；`reference` 才使用 Ref2VA 的 9 图、3 视频、3 音频与混合 12 文件上限。
- 边界：官方 H3-Context-IR 是托管预处理/编排服务，不包含在最初开放权重中。直接使用 Base 与完整托管工作流必须分开说明，不能把 Context-IR 处理结果冒充原始 Prompt。

## CLI

```text
python scripts/prompt_compiler.py list-platforms
python scripts/prompt_compiler.py audit --input project.json
python scripts/prompt_compiler.py compile --input project.json
python scripts/prompt_compiler.py compile --input project.json --platform "Seedance 2.5"
python scripts/prompt_compiler.py validate-delta --input learning/deltas/delta-xxxxxxxx.json
```

输出中的 `evidence_boundary` 必须随交付保留在审计信息里；纯执行版可不把它塞进视频模型 Prompt，但向用户报告时不得省略。
