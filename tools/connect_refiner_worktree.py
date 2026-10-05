"""Connect the local refiner to this checkout without importing or refining models."""
from pathlib import Path
import argparse
import json
import os


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refiner',type=Path,required=True)
    parser.add_argument('--python',type=Path,required=True)
    args=parser.parse_args()
    worktree=Path(__file__).resolve().parents[1]
    refiner=args.refiner.resolve()
    patches=json.loads(Path(__file__).with_name('refiner_connection.json').read_text(encoding='utf-8'))
    for filename,patch in patches.items():
        path=refiner/filename
        source=path.read_text(encoding='utf-8')
        start=source.index(patch['start'])
        end=source.index(patch['end'],start)
        source=source[:start]+patch['replacement']+source[end:]
        path.write_text(source,encoding='utf-8')
    for filename in ('launch.py','server.py'):
        path=refiner/filename
        source=path.read_text(encoding='utf-8').replace('ENGINE_VERSION=2','ENGINE_VERSION=3')
        path.write_text(source,encoding='utf-8')
    configuration={'root':os.path.relpath(args.python.resolve().parent.parent,refiner),
                   'worktree':os.path.relpath(worktree,refiner),
                   'python':os.path.relpath(args.python.resolve(),refiner)}
    (refiner/'combined-app.json').write_text(json.dumps(configuration,indent=2),encoding='utf-8')
    print('Connected. Reopen the refiner after its current refinement finishes. No models were imported.')


if __name__=='__main__':
    main()
