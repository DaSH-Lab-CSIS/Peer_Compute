export PYENV_ROOT="/home/user/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"

# Initialize pyenv (ensure it's properly initialized)
eval "$(pyenv init -)"

python ~/Documents/Serverless_Scheduler/scheduler/manage.py runserver 0.0.0.0:8000