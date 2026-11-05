# 研究基线与模块来源

- 工作区 `research/Kythera-ZZZ-Shader/`：Kythera V2、Jideeh v1.7.1，参考 Diffuse / Shader to RGB、独立脸部方向、眼部与反壳描边组织。
- 工作区 `research/jideeh_kythera_character_rendering/`：36 份角色工程与原生控制脚本，参考角色内资源组织、头部坐标、眼层与相机。
- Jideeh 固定源码：[Kytheras-ZZZ-Shader](https://github.com/Jideeh1/Kytheras-ZZZ-Shader/tree/2c3ce589d6de27b341dbd3b5cf7a350581a76628)。
- [MMD Tools](https://github.com/MMD-Blender/blender_mmd_tools)：通过其公开导入操作符读取 PMX，不重写 PMX 解析器。
- 0.1.1 的 PMX 高光读取参考已安装 MMD Tools 4.5.14 的材质实现：保留 Specular 颜色，粗糙度按 `1 / max(shininess, 1) ** 0.37` 换算。用途名称、眼部深度与相机适配由本地多角色 PMX 对照验证。
- 工作区 Hoyo-GI-Toon：参考 PMX 原语义、源数据保护、私有后台验证的实现经验；本项目的材质链路与状态独立维护。

## P0 实际核对

2026-10-31 在 Blender 5.2.3 LTS 中加载两份 V2。已提取的材质接口及默认输入、节点类型清单和连接清单一致。尚未逐一比较内部节点全部参数、动画或渲染，不据此声明两份工程完全等价。

后续增强的参考基线固定为 Discord 发布文件，SHA256 为 `0ca2238ec9b68a00c6d270666829827f839a770df8fd4b66e1c3af99d83a4c52`；GitHub 来源文件 SHA256 为 `121427d3caea03fe433d80a6a6b7bc5fde1529f5aada66bd903370955c652e72`。

V0.1 使用本项目生成的原生基础节点，不附带两份研究工程或角色资源。身体和头发沿用实际光照采样思想，脸部方向与反壳组织参考 Jideeh；游戏数据图、Closure 接口和角色 SDF 尚未接入。程序只处理明确选择的角色。

本项目候选实际验证环境为 Blender 5.2.3 LTS / MMD Tools 4.5.14。辅助插件最低版本与节点资产兼容性分别记录，不继承其宣称的其他版本支持范围。

## 0.2.0 共享 Face SDF

`materials/face.py` 将本地 Kythera V2 中已核对的三维方向点积、Float Curve、镜像 UV、R／Alpha 遮罩和两段明暗映射写成原生节点构建器。外部 Closure 提供数据采样。与原始遮罩中间输出的前、左右侧、背向控制区域最大差为 0；这不代表完整 V2 Body／Eye、调色、SSS 或轮廓光已移植。

接收器采用朝向主 Sun 的 Diffuse / Shader to RGB 受光强度，保留实际投影和环境光；没有照搬在 City-Terrace 环境光下饱和的低门限 Ramp。SDF 资源由用户显式绑定，按数据用途创建独立 Non-Color／Channel Packed 副本；源图像、PMX UV 和覆盖率保持独立。共享节点组及派生图像纳入原有归属、回滚与恢复链路。研究工程、游戏图像和角色贴图不进入安装包。

## 共用透明与基础脸影

0.1.2 使用本地 PMX、用户指定的 City-Terrace 和独立后台对照验证。原始场景、角色截图与模型只保存在私人验证目录，不分发。独立发片与后绘制共面贴花的判定来自实际源几何；基础脸影的真实遮挡响应由画面外遮挡物与可见脸部遮罩对照记录。

[Blender EEVEE 材质设置](https://docs.blender.org/manual/de/5.0/render/eevee/material_settings.html)提供 Dithered／Blended 的通用边界及混合排序说明；具体 5.2 行为以本项目实际对照为准，不据其他版本手册代替运行验证。共面最小复现、隔离高光层和失败候选均保留，不把整体切换 Dithered 的失败方案用于正式节点。

## 0.3.0 共用身体与头发重构

本地固定 Kythera V2 的 `Lit/Shadow` 子组先分别生成亮色与暗色，再由受光因子合成。其暗色保持 Hue，Saturation 使用 `(0,0) → (.25,.5) → (1,1)` 曲线，Value 使用 `(0,0) → (.625,.25) → (1,1)` 曲线，最后乘暗部色调。0.3 将这部分写成独立、受归属管理的原生调色组；原始 `_M`／`_A` 区域遮罩未对 PMX 普遍匹配，未自动接入。

[MToon 1.0 规范](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_materials_mtoon-1.0/README.md)与 [MToon 实现](https://github.com/Santarh/MToon/blob/master/MToon/Resources/Shaders/MToonCore.cginc)提供光向分区、亮暗配色与接收光颜色分开处理的参考。本项目用自己的 Blender 节点构建器实现：主 Sun 与表面法线决定分区，朝向主光的 Diffuse／Shader to RGB 提供受光强度和 RGB，PMX Toon 作为可控颜色混合，PMX Specular／Sphere 保留各自语义。

[Blender 5.2 EEVEE 节点支持](https://docs.blender.org/manual/en/5.2/render/eevee/limitations/nodes_support.html)说明 Shader to RGB 的引擎边界。本实现仍限 EEVEE；接收器包含实际场景中的补光与环境光，不声称它是分离的单灯阴影贴图。明暗分区不随 World 强度改变，实际暗部仍可被环境照明填亮。

## 质感复核后的原始材质研究

2026-10-31 私有研究补充 [HoyoToon ZZZ 着色器](https://github.com/Hoyotoon/HoyoToon/tree/main/Shaders/ZenlessZoneZero)的输入声明及 `zzz-common.hlsl`／`zzz-program.hlsl`，与 [Zenlight](https://github.com/Infused-Doggo/Zenlight) 的 `Shader/NapAvatarUI.fxsub` 交叉核对。这些是社区实现与视觉移植，不作为游戏官方源码；本项目尚未完整移植它们，也不分发其文件。

两者的主体数据语义与 Kythera 的简化效果不同：M.R 是材质区域 ID，M.G 是金属度，M.B 是高光遮罩；A.G 是光滑度，A.B 按开关用于 Matcap／自发光；N.RG 是切线法线 XY，N.B 是漫反射偏置，不能作为法线 Z 使用。Matcap 遮罩的分拆同时依赖自发光与遮罩开关，不能仅检查 `_UseMatCapMask`。这些含义已用于私有探针，不追溯声称 0.3 已接入这些输入。

资料库的原始 UI 材质 JSON 提供按区域的颜色、高光形状、光滑度和 Matcap 输入。读取原资产参数属于资源接入，与按角色手调风格预设分开；同一颜色图不证明同一原始材质。同一图集上的 Body 与 Hair_T 必须进一步匹配原始材质区域，跨文件 `m_PathID` 的唯一名字也只算候选线索，不算资产身份。

实际重做范围、失败方向和后续验收条件见 [材质输入与质感重做](../design/material-response.md)。[Blender 灯光链接手册](https://docs.blender.org/manual/id/5.0/render/lights/light_linking.html)用于独立角色灯光探针；具体 5.2 行为以本项目后台运行结果为准。

## RandomPlayToon

用户指定的 [RandomPlayToon](https://github.com/ImLaoBJie/RandomPlayToon/tree/87ebc01de7c6a1ab4796b7da7196b88830d74667) 固定在提交 `87ebc01de7c6a1ab4796b7da7196b88830d74667`，源许可证为 GPL-3.0。私有参考快照保留原许可证并核对 Git blob 摘要，没有纳入安装包。

本轮只将其 `materials/graph.py` 的共用 `build_surface` 作为隔离控制执行，并在本项目工具中依据 `materials/detail_review.py` 的共用方法建立头发图形高光与亮部柔化试验。其他源码用于只读分析；未安装或运行其完整插件、内置 PMX 导入器、角色配置和风格预设。三角色实际对照与限制见 [研究记录](../design/randomplay-reference.md)。

随后用户确认采用这一方向，0.4 将上述共用公式及 `scene_response.py` 的色度正则化接入正式 `materials/surface.py`；`source_asset_match.py` 的区域采样思路用于输入核对，另增加本项目的共享 UV 证据、范围控制和资源生命周期。原始快照仍不打包；改编部分的来源、提交和 GPL 许可已写入源码头部及 NOTICE。不包含上游角色预设、专属材质补丁或固定脸部位置。

0.5 补充研究同一提交的共用展示控制、亮暗分离和宽反射组织，实际实现三段配色、受原色约束的暗部染色、皮肤／脸部暖色与头发亮部空间。采用同一组真实主光方向和视角形成风格化反射，没有载入上游按角色保存的例外数值。三角色相同参数的原型、正式渲染与同灯光前后对照位于当前开发记录。

## 0.6 应用流程来源

Hoyo-GI-Toon 2.5.0 的六面板、场景生命周期、持久打光、原生相机／渲染与可选眼骨跟随模块在本项目适配为独立 HZZ 命名空间。两个准备好的环境资产保留原始元数据，见 `assets/scenes.json`。没有移植 GI 着色器或 GI 脸影资源。FBX 自动 UV 对应使用 Blender 自带 `io_scene_fbx.parse_fbx` 只读解析，不执行几何导入。

## 0.7 自动描边与透眼

继续固定 RandomPlayToon `87ebc01de7c6a1ab4796b7da7196b88830d74667`：参考 `feature_extension.py` 的相机平面描边、局部边长与像素上限，以及 `effects/layers.py` 的刘海域、可见眼部、深度与预乘颜色合成。保留本项目 PMX 顶点边线权重和身高倍率。

本项目自行实现基于头部坐标与语义几何的刘海／眼眶范围、标准闭眼形态键驱动、逐目标可见性场景、原场景对象同步及合成器恢复。辅助计算只替换目标角色的派生渲染网格，其他角色与场景继续遮挡；无需挪动源集合。没有引入上游按角色保存的指纹预设、固定面号、脸部场或完整角色工程。基础脸影、SDF 与身体着色保持 0.6.3 实现。

0.7.1 根据实际灰白块复现修正可见性计算。[Blender EEVEE 通道限制](https://docs.blender.org/manual/en/4.5/render/layers/passes.html#eevee-limitations)说明 `BLENDED` 材质不参与 Combined／Transparent 之外的通道。辅助场景为目标与透明遮挡物建立独立的 `DITHERED` 材质槽副本，保留实际 Alpha 和变形；主画面材质保持原渲染方法。该适配为本项目实现，非上游已验证能力。

## 0.8.0 原始头发高光扩缩（已撤回）

参考同一 RandomPlayToon 提交 `materials/feature_extension.py` 的 `hair_width`：根据原始遮罩的 4／12 基准像素扩张／收缩端点连续插值，0 保留原始遮罩。本项目仅在 FBX 引用和 UV 已核对的头发 M.B 通道接入，并继续使用原区域置信度与实际主光响应。

`materials/hair_highlights.py` 自行增加边缘柔化端点、按内容摘要复用、单张派生图长边不超过 2048、独立打包数据图及原生属性驱动。原始遮罩在默认值直接保留，派生图不覆盖用户文件；不改变底色图绘制的亮纹、脸影或身体响应，不引入上游角色预设。

上述为历史版本记录。用户随后要求去掉此更新，0.8.1 已移除该模块、材质接入和面板，恢复 0.7.1 的 `materials/surface.py`；保留旧包与验证记录用于追溯。
