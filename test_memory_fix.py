import json
import os

profile_path = os.path.expanduser('~/.castorice/user_profile.json')
if os.path.exists(profile_path):
    with open(profile_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if data.get('identity', {}).get('name') == '谁还记得么':
        data['identity']['name'] = ''
        data['identity']['nickname'] = ''
        with open(profile_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print('已清理错误的用户画像数据')
    else:
        print('用户画像数据正常')
else:
    print('用户画像文件不存在')

print('\n=== 测试开始 ===')

from castorice.main import CastoriceEngine

engine = CastoriceEngine()
session_id = engine.short_term.create_session()

print('\n测试1: 输入"我是谁你还记得么"')
state = engine.agent.run('我是谁你还记得么', session_id=session_id)
name_after = engine.user_profile.get('identity.name', '')
print(f'结果: {state.final_answer[:50]}')
print(f'用户名字: "{name_after}"')
assert name_after == '', f'错误！名字被错误提取为 "{name_after}"'
print('✓ 测试1通过: 疑问句没有被误提取为名字')

print('\n测试2: 输入"我叫张三"')
state = engine.agent.run('我叫张三', session_id=session_id)
name_after = engine.user_profile.get('identity.name', '')
print(f'结果: {state.final_answer[:50]}')
print(f'用户名字: "{name_after}"')
assert name_after == '张三', f'错误！名字应该是"张三"，实际是"{name_after}"'
print('✓ 测试2通过: 正确提取名字"张三"')

print('\n测试3: 输入"我是学生"')
state = engine.agent.run('我是学生', session_id=session_id)
name_after = engine.user_profile.get('identity.name', '')
print(f'结果: {state.final_answer[:50]}')
print(f'用户名字: "{name_after}"')
assert name_after == '张三', f'错误！名字不应该被覆盖为"{name_after}"'
print('✓ 测试3通过: 职业描述没有覆盖名字')

print('\n测试4: 多轮对话')
state = engine.agent.run('你好', session_id=session_id)
print(f'回复1: {state.final_answer[:50]}')
state = engine.agent.run('今天天气怎么样', session_id=session_id)
print(f'回复2: {state.final_answer[:50]}')
state = engine.agent.run('谢谢', session_id=session_id)
print(f'回复3: {state.final_answer[:50]}')
print('✓ 测试4通过: 多轮对话正常')

engine.cleanup()
print('\n=== 所有测试通过！===')
