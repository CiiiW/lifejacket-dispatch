from pathlib import Path
import subprocess,sys,json
R=Path.home()/'aerial-data/model-comparison-v1';R.mkdir(parents=True,exist_ok=True)
env=R/'env'
subprocess.run([str(Path.home()/'.venvs/aerial/bin/python'),'-m','venv','--system-site-packages',str(env)],check=True)
env_site=next((env/'lib').glob('python*/site-packages'))
aerial_site=next((Path.home()/'.venvs/aerial/lib').glob('python*/site-packages'))
(env_site/'aerial_parent.pth').write_text(str(aerial_site)+'\n')
python=env/'bin/python'
subprocess.run([str(python),'-m','pip','install','--no-deps','ultralytics==8.4.215','ultralytics-thop==2.2.5','ftfy==6.3.1'],check=True)
subprocess.run([str(python),'-m','pip','install','--no-deps','git+https://github.com/openai/CLIP.git@d05afc436d78f1c48dc0dbf8e5980a9d471f35f6'],check=True)
(R/'env-ready.txt').write_text(str(python))
print('Model environment ready',flush=True)
