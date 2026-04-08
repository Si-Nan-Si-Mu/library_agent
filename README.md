# library_agent

基于 [Rasa](https://rasa.com/) 的中文医院场景对话助手示例：挂号、查询医生排班、缴费、症状咨询，以及 FAQ 检索回复。

## 功能概览

| 能力 | 说明 |
|------|------|
| 挂号 | 收集医生、患者、科室、日期后确认并模拟调用接口 |
| 查询排班 | 收集医生、科室、日期后返回示例排班文案 |
| 缴费 | 收集患者与支付方式后模拟缴费结果 |
| 症状查询 | 收集症状与年龄后返回示例健康提示（演示用，非医疗诊断） |
| FAQ | 使用检索意图（`faq/*`）与 `ResponseSelector` 匹配常见问答 |

自定义动作逻辑见 [`actions/actions.py`](actions/actions.py)。当前「接口成功/失败」为槽位规则演示（例如指定医生名、科室、支付方式等），接入真实 HIS 时需替换为 HTTP/RPC 调用。

## 环境要求

- Python 3.8+（与所用 Rasa 版本一致即可）
- 依赖：`rasa`、`rasa-sdk`；若使用仓库内脚本另需 `flask`、`requests`

训练管线在 [`config.yml`](config.yml) 中配置了 **Jieba** 分词与 **BERT** 特征（`LanguageModelFeaturizer`，权重路径 `./models/bert-base-chinese-tf`）。首次训练前请自备该目录下的模型文件，或按需在 `config.yml` 中改为其他权重/关闭该组件。

## 常用命令

在项目根目录执行：

```bash
# 训练 NLU + Core
rasa train

# 启动 Action 服务（自定义动作）
rasa run actions --port 5055

# 启动 Rasa API（需先在 endpoints.yml 中取消注释 action_endpoint，指向上述地址）
rasa run --enable-api --cors "*" --port 5005
```

与机器人对话可使用 Rasa Shell、REST 渠道，或修改 [`run_rasa_client.py`](run_rasa_client.py) 中的 `SERVER_URL` 后运行：

```bash
python run_rasa_client.py
```

将 `SERVER_URL` 改为本机 `http://127.0.0.1:5005/model/parse` 或与部署环境一致的地址。

## 仓库内其他脚本

- [`run_rasa_server.py`](run_rasa_server.py)：独立 Flask 服务，将用户文本转发到本地 `5005` 的 `/model/parse`，再按意图 `call` / `query` 路由到 `7001` / `7002`。与本项目主域（挂号、缴费等）意图集合不同，适用于单独的 NLU 分发演示；使用前请确认下游服务已就绪。

## 目录结构（简要）

```
├── actions/actions.py   # 自定义 Action 与表单校验占位
├── config.yml           # NLU / Policy 管线
├── domain.yml           # 意图、实体、槽位、表单与回复
├── data/                # nlu、stories、rules、responses、词典等
├── tests/               # 测试用 story 数据
├── endpoints.yml        # Action Server 等端点（默认注释）
└── credentials.yml      # 渠道凭证（含 REST）
```

## 远程仓库

```text
git@github.com:Si-Nan-Si-Mu/library_agent.git
```

## 免责声明

症状相关回复仅为对话演示，不能替代专业诊疗；生产环境请务必对接合规医疗系统并加入审核与免责流程。
