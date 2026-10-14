"""Run one headless Claude Code agent billed to Anthropic API (Console) credits instead of a claude.ai plan.

    python tools/api_agent.py "task"                                   read-only agent (read, search, web)
    python tools/api_agent.py --write "task"                           may also edit files
    python tools/api_agent.py --model sonnet --budget 2 "task"         cheaper model, $2 cap
    python tools/api_agent.py "task" -- --allowedTools "Bash(git log:*)"   anything after -- goes to claude

The key comes from ANTHROPIC_CREDITS_API_KEY. It is not called ANTHROPIC_API_KEY on purpose: a cloud session ignores
that name for its own billing, and on your own machine it would move every `claude` you start onto the key.

The agent gets a scrubbed environment and a config directory of its own, so it cannot inherit a cloud session's
subscription routing (ANTHROPIC_BASE_URL and the rest) or a claude.ai login. The key is the only credential it can
see, and claude -p always uses ANTHROPIC_API_KEY when it is set. --budget stops the run once it has spent that much.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

KEY='ANTHROPIC_CREDITS_API_KEY'
# Only what the agent needs to run and reach the network. Every ANTHROPIC_* and CLAUDE_* variable of the session
# that launches it stays behind.
PASS=('PATH','HOME','USER','USERNAME','SHELL','LANG','LC_ALL','TERM','TMPDIR','TEMP','TMP',
      'USERPROFILE','APPDATA','LOCALAPPDATA','SYSTEMROOT','COMSPEC','PATHEXT',
      'HTTPS_PROXY','HTTP_PROXY','NO_PROXY','https_proxy','http_proxy','no_proxy',
      'NODE_EXTRA_CA_CERTS','SSL_CERT_FILE')


def main():
    argv=sys.argv[1:]
    extra=argv[argv.index('--')+1:] if '--' in argv else []
    argv=argv[:argv.index('--')] if '--' in argv else argv
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('task',nargs='?',help='what the agent should do; read from stdin when left out')
    parser.add_argument('--model',default='opus',help='a claude alias (opus, sonnet, haiku) or a full model ID')
    parser.add_argument('--effort',choices=('low','medium','high','xhigh','max'))
    parser.add_argument('--budget',type=float,default=5.0,help='stop after spending this many US dollars (default 5)')
    parser.add_argument('--write',action='store_true',help='let the agent edit files (default: read-only)')
    parser.add_argument('--json',action='store_true',help="print Claude Code's whole JSON result")
    args=parser.parse_args(argv)
    key=os.environ.get(KEY)
    if not key:
        sys.exit(f'api_agent: set {KEY} to a Claude Console API key first')
    claude=shutil.which('claude')
    if not claude:
        sys.exit('api_agent: the claude CLI is not on PATH')
    task=args.task if args.task is not None else sys.stdin.read()
    env={name:os.environ[name] for name in PASS if name in os.environ}
    env['ANTHROPIC_API_KEY']=key
    env['CLAUDE_CONFIG_DIR']=str(Path.home()/'.claude-api-agent')
    command=[claude,'-p','--output-format','json','--model',args.model,'--max-budget-usd',str(args.budget),
             '--permission-mode','acceptEdits' if args.write else 'default']
    if args.effort:
        command+=['--effort',args.effort]
    run=subprocess.run(command+extra,input=task,env=env,capture_output=True,text=True,encoding='utf-8')
    try:
        result=json.loads(run.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(run.stderr or run.stdout)
        sys.exit(run.returncode or 1)
    print(json.dumps(result,indent=2) if args.json else result.get('result',''))
    cost=result.get('total_cost_usd')
    spent=f'${cost:.4f}' if isinstance(cost,(int,float)) else 'unknown cost'
    print(f"api_agent: {args.model}, {result.get('num_turns','?')} turns, {spent} of API credit",file=sys.stderr)
    sys.exit(1 if result.get('is_error') else 0)


if __name__=='__main__':
    main()
