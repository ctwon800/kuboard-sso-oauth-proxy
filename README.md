## kuboard-sso-oauth-proxy

一个将 Kuboard 的 GitLab OAuth 流程“代理/仿真”到 Casdoor 的轻量服务。它向 Kuboard 暴露 GitLab 风格的接口（/oauth/authorize、/oauth/token、/api/v4/user、/api/v4/groups），实际从 Casdoor 拉取用户信息并做字段映射，帮助 Kuboard 使用 Casdoor 做单点登录。

### 项目地址

- GitHub: [ctwon800/kuboard-sso-oauth-proxy](https://github.com/ctwon800/kuboard-sso-oauth-proxy)

### 项目目的

- 使用 Casdoor 作为统一身份源，让 Kuboard 以“GitLab Provider”的模式完成登录，而无需真实 GitLab。
- 提供与 Kuboard 兼容的最小 GitLab 风格接口集（用户信息、组信息等）。
- 尽量无状态、轻量、易部署，便于快速接入与演示验证。

### 适用场景

- 企业已有 Casdoor，想让 Kuboard 通过 GitLab OAuth 模式完成 SSO。
- 不想维护/暴露真实 GitLab，仅需要提供 Kuboard 登录所需的最小接口。
- 希望按 Casdoor 用户资料推导“组”用于 Kuboard 前端展示。

### 工作原理（简述）

1. Kuboard 跳转到本服务的 `/oauth/authorize`，本服务再重定向到 Casdoor 登录页。
2. Kuboard 用授权码请求本服务 `/oauth/token`，本服务转发到 Casdoor token 接口并返回 GitLab 期望字段。
3. Kuboard 请求 `/api/v4/user` 获取“GitLab 风格”的用户信息，本服务以 Casdoor 用户信息为源做字段映射，并确保返回 `id` 为整型。
4. Kuboard 可能访问 `/oauth/userinfo`，本服务代理到 Casdoor 并补充 `groups` 字段，或直接调用 `/api/v4/groups` 获取组列表。

### 特性

- 轻量、无数据库依赖；仅依赖 Casdoor 用户信息接口。
- 兼容多种 Casdoor 返回结构（包含 `{ data: {...} }`）。
- 自动从 Casdoor 用户资料推导组名（organizations/groups/roles/organization/owner 等）。
- Docker 化部署，配置简单。


### 快速开始

- 使用 Docker Compose（推荐）

```bash
# 1) 编辑 docker-compose.yml，将 environment 中的值改为你的实际配置
# 2) 一键启动
docker compose up -d

# 查看日志
docker compose logs -f
```

- 使用 docker run（单条命令）

```bash
docker run --rm -p 8080:8080 \
  -e CLIENT_ID="your_casdoor_client_id" \
  -e CLIENT_SECRET="your_casdoor_client_secret" \
  -e REDIRECT_URI="https://kuboard.example.com/sso/callback" \
  -e CASDOOR_BASE="https://casdoor.example.com" \
  -e CASDOOR_SCOPE="openid profile email" \
  -e CASDOOR_AUTH="https://casdoor.example.com/login/oauth/authorize" \
  -e CASDOOR_TOKEN_URL="https://casdoor.example.com/api/login/oauth/access_token" \
  -e CASDOOR_USERINFO_URL="https://casdoor.example.com/api/get-account" \
  -e GITLAB_BASE="https://gitlab.example.com" \
  ctwon800/kuboard-sso-oauth-proxy:latest
```

- 从源码运行（可选）

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export CLIENT_ID=... CLIENT_SECRET=... REDIRECT_URI=...
python proxy.py
```

### 环境变量说明（启动参数）

- **CLIENT_ID**: Casdoor 应用的 Client ID（必填）。
- **CLIENT_SECRET**: Casdoor 应用的 Client Secret（必填）。
- **REDIRECT_URI**: Kuboard 配置的回调地址（必填），与 Kuboard SSO 配置保持一致。
- **CASDOOR_BASE**: Casdoor 基础地址，便于构造默认接口地址，默认 `https://casdoor.example.com`。
- **CASDOOR_SCOPE**: OAuth scope，默认 `openid profile email`。
- **CASDOOR_AUTH**: Casdoor 授权端点，默认 `${CASDOOR_BASE}/login/oauth/authorize`。
- **CASDOOR_TOKEN_URL**: Casdoor 令牌端点，默认 `${CASDOOR_BASE}/api/login/oauth/access_token`。
- **CASDOOR_USERINFO_URL**: Casdoor 用户信息端点，默认 `${CASDOOR_BASE}/api/get-account`。
- **GITLAB_BASE**: 仅用于返回组的 `web_url` 拼接，默认 `https://gitlab.example.com`。

### 脚本与端点的作用

本项目核心脚本：`proxy.py`

对外暴露以下端点（Kuboard 会按 GitLab 方式调用）：

- `GET /oauth/authorize`
  - 作用：将浏览器重定向至 Casdoor 登录页。
  - 入参：Kuboard 传入 `state` 等参数。

- `POST /oauth/token`
  - 作用：Kuboard 用授权码换取访问令牌，服务端把请求转发到 Casdoor 的 token 接口，并返回 GitLab 期望的字段：`access_token`、`token_type`、`expires_in`。

- `GET /oauth/userinfo`
  - 作用：兼容性端点。某些场景下 Kuboard 会错误请求该路径，这里直接代理到 `CASDOOR_USERINFO_URL` 并原样返回 Casdoor 用户信息。

- `GET /api/v4/user`
  - 作用：返回“GitLab 风格”的用户信息，字段来源于 Casdoor 用户信息并做映射，例如：`id/username/email/name/avatar_url/state` 等。
  - 认证：从请求头 `Authorization: Bearer <token>` 读取令牌，去 Casdoor 拉取信息。

- `GET /api/v4/groups`
  - 作用：返回“GitLab 风格”的用户组列表。根据 Casdoor 用户信息的以下字段推导组名（去重）：
    - `organizations/orgs`（对象数组，取 `name/displayName/id`）
    - `groups`（对象或字符串数组）
    - `roles`（对象或字符串数组）
    - `organization/owner/tenant/org`（字符串）
    - 若均无，则回退为用户的 `displayName/name/username/default`
  - `path` 通过组名 slug 化生成；`web_url` 使用 `GITLAB_BASE` 拼接。
  - 认证：同上，读取 `Authorization: Bearer <token>`。

### 与 Kuboard 对接指引（示例）

将 Kuboard 的“GitLab OAuth Provider”指向本服务：

- Authorization URL: `https://<your-proxy-domain>/oauth/authorize`
- Token URL: `https://<your-proxy-domain>/oauth/token`
- （Kuboard 访问用户信息/组信息时，会用 GitLab 预期的路径命中本服务的 `/api/v4/user` 与 `/api/v4/groups`）

确保 `CLIENT_ID/CLIENT_SECRET/REDIRECT_URI` 与 Casdoor/Kuboard 的实际配置一致。

### 开发/调试建议

- 本地可直接 `python proxy.py` 启动，或配合 `gunicorn`/容器化部署。
- 若需要调试请求链路，建议抓取 `Authorization` 请求头并在 Casdoor 后台确认 token 与用户信息是否匹配。


### 许可证

MIT（若有不同要求，请自行修改）。

### Docker 构建与运行

1) 构建镜像

```bash
docker build -t kuboard-sso-oauth-proxy:latest .
```

2) 运行容器（示例）

```bash
docker run --rm -p 8080:8080 \
  -e CLIENT_ID="your_casdoor_client_id" \
  -e CLIENT_SECRET="your_casdoor_client_secret" \
  -e REDIRECT_URI="https://kuboard.example.com/sso/callback" \
  -e CASDOOR_BASE="https://casdoor.example.com" \
  -e CASDOOR_SCOPE="openid profile email" \
  -e CASDOOR_AUTH="https://casdoor.example.com/login/oauth/authorize" \
  -e CASDOOR_TOKEN_URL="https://casdoor.example.com/api/login/oauth/access_token" \
  -e CASDOOR_USERINFO_URL="https://casdoor.example.com/api/get-account" \
  -e GITLAB_BASE="https://gitlab.example.com" \
  kuboard-sso-oauth-proxy:latest
```

也可以使用环境文件：

```bash
cat > .env <<'EOF'
CLIENT_ID=your_casdoor_client_id
CLIENT_SECRET=your_casdoor_client_secret
REDIRECT_URI=https://kuboard.example.com/sso/callback
CASDOOR_BASE=https://casdoor.example.com
CASDOOR_SCOPE=openid profile email
CASDOOR_AUTH=https://casdoor.example.com/login/oauth/authorize
CASDOOR_TOKEN_URL=https://casdoor.example.com/api/login/oauth/access_token
CASDOOR_USERINFO_URL=https://casdoor.example.com/api/get-account
GITLAB_BASE=https://gitlab.example.com
EOF

docker run --rm -p 8080:8080 --env-file ./.env kuboard-sso-oauth-proxy:latest
```

<!-- CodeRabbit integration test -->
