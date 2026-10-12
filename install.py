"""Install discoverable skills by symlink; never replace an unrelated skill."""
import argparse,os,pathlib
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--codex-home',default=os.environ.get('CODEX_HOME',str(pathlib.Path.home()/'.codex')));a=p.parse_args()
root=pathlib.Path(__file__).resolve().parent
for src in sorted((root/'skills').iterdir()):
 if not (src/'SKILL.md').is_file():continue
 dst=pathlib.Path(a.codex_home).expanduser()/'skills'/src.name;dst.parent.mkdir(parents=True,exist_ok=True)
 if dst.is_symlink() and dst.resolve()==src.resolve():print('Already installed:',dst);continue
 if dst.exists() or dst.is_symlink():raise SystemExit('Refusing to replace existing skill: '+str(dst))
 dst.symlink_to(src,target_is_directory=True);print('Installed:',dst)
