from flask import Flask, request, redirect, jsonify
import requests
import os
import re
import hashlib

app = Flask(__name__)

# === Casdoor 配置 ===
CASDOOR_BASE = os.getenv("CASDOOR_BASE", "https://casdoor.example.com")
CLIENT_ID = os.getenv("CLIENT_ID", "your_casdoor_client_id")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "your_casdoor_client_secret")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://kuboard.example.com/sso/callback")
CASDOOR_SCOPE = os.getenv("CASDOOR_SCOPE", "openid profile email")
CASDOOR_AUTH = os.getenv("CASDOOR_AUTH", "https://casdoor.example.com/login/oauth/authorize")
CASDOOR_TOKEN_URL = os.getenv("CASDOOR_TOKEN_URL", "https://casdoor.example.com/api/login/oauth/access_token")
CASDOOR_USERINFO_URL = os.getenv("CASDOOR_USERINFO_URL", "https://casdoor.example.com/api/get-account")

# GitLab 基础地址（用于拼接返回的 web_url），可选
GITLAB_BASE = os.getenv("GITLAB_BASE", "https://gitlab.example.com")



# Kuboard 会请求 /oauth/authorize
@app.route("/oauth/authorize")
def authorize():
    state = request.args.get("state", "")
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": CASDOOR_SCOPE,
        "state": request.args.get("state", ""),
    }
    # 直接跳转 Casdoor 登录页
    r = requests.Request("GET", CASDOOR_AUTH, params=params).prepare()
    return redirect(r.url)

# Kuboard 会请求 /oauth/token
@app.route("/oauth/token", methods=["POST"])
def token():
    code = request.form.get("code")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post(CASDOOR_TOKEN_URL, data=data, headers={"Accept": "application/json"})
    token_data = resp.json()

    # Casdoor 返回的字段名兼容性处理
    # Kuboard 期望有 access_token、token_type
    result = {
        "access_token": token_data.get("access_token") or token_data.get("data", {}).get("accessToken"),
        "token_type": "bearer",
        "expires_in": token_data.get("expires_in", 604800),
    }
    return jsonify(result)




@app.route("/oauth/userinfo")
def oauth_userinfo():
    # 为适配 Kuboard 展示用户组，此处不再原样透传，而是补充 groups 字段
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if not token:
        token = request.headers.get("PRIVATE-TOKEN", "").strip()
    if not token:
        token = request.args.get("access_token") or request.args.get("token") or ""
        token = token.strip()

    if not token:
        return jsonify({"error": "missing access token"}), 401

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(f"{CASDOOR_USERINFO_URL}", headers=headers, timeout=5)

    if resp.status_code != 200:
        return jsonify({"error": "failed to get userinfo", "details": resp.text}), 500

    cas_user = resp.json()
    if isinstance(cas_user, dict) and isinstance(cas_user.get("data"), dict) and not cas_user.get("id"):
        cas_user = cas_user.get("data", {})

    # 组名提取逻辑与 /api/v4/groups 保持一致
    candidate_names = []

    orgs = cas_user.get("organizations") or cas_user.get("orgs")
    if isinstance(orgs, list):
        for item in orgs:
            if isinstance(item, dict):
                name = item.get("name") or item.get("displayName") or item.get("id")
                if name:
                    candidate_names.append(str(name))

    groups_field = cas_user.get("groups")
    if isinstance(groups_field, list):
        for item in groups_field:
            if isinstance(item, dict):
                name = item.get("name") or item.get("displayName") or item.get("id")
                if name:
                    candidate_names.append(str(name))
            elif isinstance(item, str):
                candidate_names.append(item)
    elif isinstance(groups_field, str):
        for piece in re.split(r"[,;\s]+", groups_field):
            if piece:
                candidate_names.append(piece)

    roles = cas_user.get("roles")
    if isinstance(roles, list):
        for item in roles:
            if isinstance(item, dict):
                name = item.get("name") or item.get("displayName") or item.get("id")
                if name:
                    candidate_names.append(str(name))
            elif isinstance(item, str):
                candidate_names.append(item)
    elif isinstance(roles, str):
        for piece in re.split(r"[,;\s]+", roles):
            if piece:
                candidate_names.append(piece)

    for k in [
        "organization", "owner", "tenant", "org", "group", "departments", "teams", "permissions", "projects",
    ]:
        val = cas_user.get(k)
        if isinstance(val, str) and val:
            for piece in re.split(r"[,;\s]+", val):
                if piece:
                    candidate_names.append(piece)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("displayName") or item.get("id")
                    if name:
                        candidate_names.append(str(name))
                elif isinstance(item, str):
                    candidate_names.append(item)

    seen = set()
    unique_names = []
    for n in candidate_names:
        key = n.strip()
        if key and key not in seen:
            seen.add(key)
            unique_names.append(key)

    enriched = dict(cas_user)
    # 若原有 groups 为对象/混合，仍然统一补充一个扁平字符串数组字段
    enriched["groups"] = unique_names

    # 兼容一些不同字段名的邮箱
    if not enriched.get("email"):
        if isinstance(enriched.get("mail"), str):
            enriched["email"] = enriched.get("mail")
        elif isinstance(enriched.get("primaryEmail"), str):
            enriched["email"] = enriched.get("primaryEmail")
        elif isinstance(enriched.get("emails"), list) and enriched.get("emails"):
            first = enriched.get("emails")[0]
            if isinstance(first, str):
                enriched["email"] = first
            elif isinstance(first, dict):
                # 常见结构 { value/email }
                enriched["email"] = first.get("email") or first.get("value")
    return jsonify(enriched)

# Kuboard 会请求 /api/v4/user
@app.route("/api/v4/user")
def userinfo():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(f"{CASDOOR_USERINFO_URL}", headers=headers)
    cas_user = resp.json()
    if isinstance(cas_user, dict) and isinstance(cas_user.get("data"), dict) and not cas_user.get("id"):
        cas_user = cas_user.get("data", {})

    # 兼容邮箱字段名差异
    email_value = (
        cas_user.get("email")
        or cas_user.get("mail")
        or cas_user.get("primaryEmail")
    )
    if not email_value:
        emails_field = cas_user.get("emails")
        if isinstance(emails_field, list) and emails_field:
            first = emails_field[0]
            if isinstance(first, str):
                email_value = first
            elif isinstance(first, dict):
                email_value = first.get("email") or first.get("value")

    # 转换为 GitLab 风格字段
    # 生成整型 ID（GitLab 期望为 int）：
    raw_id = cas_user.get("id")
    int_id = None
    if isinstance(raw_id, int):
        int_id = raw_id
    elif isinstance(raw_id, str):
        if raw_id.isdigit():
            try:
                int_id = int(raw_id)
            except Exception:
                int_id = None
    if int_id is None:
        # 基于可用标识生成稳定的正整型（32-bit）
        identity_seed = (
            str(raw_id)
            or cas_user.get("username")
            or cas_user.get("name")
            or (email_value or "")
            or "default"
        )
        digest = hashlib.sha256(identity_seed.encode("utf-8")).digest()
        int_id = (int.from_bytes(digest[:8], "big") & 0x7FFFFFFF) or 1

    mapped = {
        "id": int_id,
        "username": cas_user.get("username") or cas_user.get("name"),
        "email": email_value or "",
        "name": cas_user.get("displayName") or cas_user.get("name"),
        "state": "active",
        "avatar_url": cas_user.get("avatar") or cas_user.get("avatarUrl") or cas_user.get("photo") or "",
    }
    return jsonify(mapped)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)