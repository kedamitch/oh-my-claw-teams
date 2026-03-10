import json, sys, os, re
from datetime import datetime

def sync():
    path = os.environ.get('CONFIG_FILE', '/home/node/.openclaw/openclaw.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        env = os.environ
        
        def ensure_path(cfg, keys):
            curr = cfg
            for k in keys:
                if k not in curr: curr[k] = {}
                curr = curr[k]
            return curr

        # --- 0. 飞书旧版本格式迁移 ---
        feishu_raw = config.get('channels', {}).get('feishu', {})
        if 'appId' in feishu_raw and 'accounts' not in feishu_raw:
            print('检测到飞书旧版本格式，执行迁移...')
            old_app_id = feishu_raw.pop('appId', '')
            old_app_secret = feishu_raw.pop('appSecret', '')
            old_bot_name = feishu_raw.pop('botName', 'OpenClaw Bot')
            feishu_raw['accounts'] = {'default': {'appId': old_app_id, 'appSecret': old_app_secret, 'botName': old_bot_name}}

        # 飞书账号键名兼容：将 accounts.main 归一到 accounts.default
        feishu_accounts = feishu_raw.get('accounts')
        if isinstance(feishu_accounts, dict) and 'main' in feishu_accounts:
            print('检测到飞书 accounts.main，迁移为 accounts.default...')
            main_account = feishu_accounts.pop('main')
            default_account = feishu_accounts.get('default')
            if not isinstance(default_account, dict):
                feishu_accounts['default'] = main_account if isinstance(main_account, dict) else {}
            elif isinstance(main_account, dict):
                for k, v in main_account.items():
                    default_account.setdefault(k, v)


        # --- 1. 模型同步 ---
        sync_model = env.get('SYNC_MODEL_CONFIG', 'true').strip().lower()
        if sync_model in ('', 'true', '1', 'yes'):
            def sync_provider(p_name, api_key, base_url, protocol, m_ids_str, context_window, max_tokens):
                if not (api_key and base_url or m_ids_str): return None
                p = ensure_path(config, ['models', 'providers', p_name])
                if api_key: p['apiKey'] = api_key
                if base_url: p['baseUrl'] = base_url
                p['api'] = protocol or 'openai-completions'
                
                mlist = p.get('models', [])
                m_ids = [x.strip() for x in m_ids_str.split(',') if x.strip()]
                
                for m_id in m_ids:
                    # 保留完整模型 ID（例如 minimaxai/minimax-m2.5），不要按 / 截断
                    actual_m_id = m_id

                    m_obj = next((m for m in mlist if m.get('id') == actual_m_id), None)
                    if not m_obj:
                        m_obj = {'id': actual_m_id, 'name': actual_m_id, 'reasoning': False, 'input': ['text', 'image'],
                                 'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}
                        mlist.append(m_obj)
                    m_obj['contextWindow'] = int(context_window or 200000)
                    m_obj['maxTokens'] = int(max_tokens or 8192)
                
                p['models'] = mlist
                return p_name

            # Provider 1 (default)
            p1_active = sync_provider(
                'default', 
                env.get('API_KEY'), 
                env.get('BASE_URL'), 
                env.get('API_PROTOCOL'), 
                env.get('MODEL_ID') or 'gpt-4o',
                env.get('CONTEXT_WINDOW'),
                env.get('MAX_TOKENS')
            )
            
            # Provider 2
            p2_name = env.get('MODEL2_NAME') or 'model2'
            p2_active = sync_provider(
                p2_name,
                env.get('MODEL2_API_KEY'),
                env.get('MODEL2_BASE_URL'),
                env.get('MODEL2_PROTOCOL'),
                env.get('MODEL2_MODEL_ID') or '',
                env.get('MODEL2_CONTEXT_WINDOW'),
                env.get('MODEL2_MAX_TOKENS')
            )

            # 同步更新默认模型
            mid_raw = env.get('MODEL_ID') or 'gpt-4o'
            # 获取第一个模型 ID 作为默认 primary
            mid = [x.strip() for x in mid_raw.split(',') if x.strip()][0]
            
            imid_raw = env.get('IMAGE_MODEL_ID') or mid
            imid = [x.strip() for x in imid_raw.split(',') if x.strip()][0]
            
            def get_full_mid(m_id, default_p='default'):
                if '/' in m_id: return m_id
                return f'{default_p}/{m_id}'

            if p1_active:
                ensure_path(config, ['agents', 'defaults', 'model'])['primary'] = get_full_mid(mid)
                ensure_path(config, ['agents', 'defaults', 'imageModel'])['primary'] = get_full_mid(imid)
            
            # 工作区同步：存在则更新，不存在则恢复默认
            config['agents']['defaults']['workspace'] = env.get('WORKSPACE') or '/home/node/.openclaw/workspace'
            
            # 同步更新 memory 路径
            if 'memory' in config and 'qmd' in config['memory']:
                config['memory']['qmd']['command'] = '/usr/local/bin/qmd'
                for p_item in config['memory']['qmd'].get('paths', []):
                    if p_item.get('name') == 'workspace':
                        p_item['path'] = config['agents']['defaults']['workspace']
            
            msg = f'✅ 模型同步完成: 主模型={get_full_mid(mid)}'
            if imid != mid: msg += f', 图片模型={get_full_mid(imid)}'
            if p2_active: msg += f', 已启用备用提供商: {p2_name}'
            print(msg)

        # --- 2. 渠道与插件同步 (声明式) ---
        channels = ensure_path(config, ['channels'])
        plugins = ensure_path(config, ['plugins'])
        entries = ensure_path(plugins, ['entries'])
        installs = ensure_path(plugins, ['installs'])

        if env.get('OPENCLAW_PLUGINS_ENABLED'):
            plugins['enabled'] = env['OPENCLAW_PLUGINS_ENABLED'].lower() == 'true'
        
        def sync_feishu(c, e):
            c.update({'enabled': True, 'dmPolicy': 'pairing', 'groupPolicy': 'open'})
            default_account = ensure_path(c, ['accounts', 'default'])
            default_account.update({
                'appId': e['FEISHU_APP_ID'],
                'appSecret': e['FEISHU_APP_SECRET'],
                'botName': e.get('FEISHU_BOT_NAME') or 'OpenClaw Bot'
            })
            if e.get('FEISHU_DOMAIN'): default_account['domain'] = e['FEISHU_DOMAIN']

        def sync_dingtalk(c, e):
            c.update({
                'enabled': True, 'clientId': e['DINGTALK_CLIENT_ID'], 
                'clientSecret': e['DINGTALK_CLIENT_SECRET'],
                'robotCode': e.get('DINGTALK_ROBOT_CODE') or e['DINGTALK_CLIENT_ID'],
                'dmPolicy': 'open', 'groupPolicy': 'open', 'messageType': 'markdown',
                'allowFrom': ['*']
            })
            if e.get('DINGTALK_CORP_ID'): c['corpId'] = e['DINGTALK_CORP_ID']
            if e.get('DINGTALK_AGENT_ID'): c['agentId'] = e['DINGTALK_AGENT_ID']


        # 同步规则矩阵
        sync_rules = [
            (['FEISHU_APP_ID', 'FEISHU_APP_SECRET'], 'feishu', sync_feishu,
             {'source': 'npm', 'spec': '@openclaw/feishu', 'installPath': '/home/node/.openclaw/extensions/feishu'}),
            (['DINGTALK_CLIENT_ID', 'DINGTALK_CLIENT_SECRET'], 'dingtalk', sync_dingtalk,
             {'source': 'npm', 'spec': 'https://github.com/soimy/clawdbot-channel-dingtalk.git', 'installPath': '/home/node/.openclaw/extensions/dingtalk'})
        ]

        for req_envs, cid, config_fn, install_info in sync_rules:
            has_env = all(env.get(k) for k in req_envs)
            if has_env:
                conf_obj = ensure_path(channels, [cid])
                config_fn(conf_obj, env)
                entries[cid] = {'enabled': True}
                if install_info and cid not in installs:
                    install_info['installedAt'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                    installs[cid] = install_info
                print(f'✅ 渠道同步: {cid}')
            else:
                if cid in entries and entries[cid].get('enabled'):
                    entries[cid]['enabled'] = False
                    print(f'🚫 环境变量缺失，已禁用渠道: {cid}')

        # 汇总所有已启用的插件到 allow 列表
        plugins['allow'] = [k for k, v in entries.items() if v.get('enabled')]
        print('📦 已配置插件集合: ' + ', '.join(plugins['allow']))


        # --- 3. Gateway 同步 ---
        if env.get('OPENCLAW_GATEWAY_TOKEN'):
            gw = ensure_path(config, ['gateway'])
            gw['port'] = int(env.get('OPENCLAW_GATEWAY_PORT') or 18789)
            gw['bind'] = env.get('OPENCLAW_GATEWAY_BIND') or '0.0.0.0'
            gw['mode'] = env.get('OPENCLAW_GATEWAY_MODE') or 'local'
            
            # --- Control UI 配置 ---
            cui = ensure_path(gw, ['controlUi'])
            cui['allowInsecureAuth'] = env.get('OPENCLAW_GATEWAY_ALLOW_INSECURE_AUTH', 'true').lower() == 'true'
            cui['dangerouslyDisableDeviceAuth'] = env.get('OPENCLAW_GATEWAY_DANGEROUSLY_DISABLE_DEVICE_AUTH', 'false').lower() == 'true'
            if env.get('OPENCLAW_GATEWAY_ALLOWED_ORIGINS'):
                cui['allowedOrigins'] = [x.strip() for x in env['OPENCLAW_GATEWAY_ALLOWED_ORIGINS'].split(',') if x.strip()]
            
            auth = ensure_path(gw, ['auth'])
            auth['token'] = env['OPENCLAW_GATEWAY_TOKEN']
            auth['mode'] = env.get('OPENCLAW_GATEWAY_AUTH_MODE') or 'token'

            print('✅ Gateway 同步完成')

        # 保存并更新时间戳
        ensure_path(config, ['meta'])['lastTouchedAt'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        print(f'❌ 同步失败: {e}', file=sys.stderr)
        sys.exit(1)

sync()
