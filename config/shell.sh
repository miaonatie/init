# Managed by init. Edit the repository copy, then rerun: python3 init.py

path_prepend() {
  [ -n "$1" ] || return 0
  case ":$PATH:" in
    *":$1:"*) ;;
    *) PATH="$1:$PATH" ;;
  esac
}

path_prepend "$HOME/.local/bin"
path_prepend "$HOME/.local/share/init/venv/bin"

# Ruby --user-install binaries.
for init_gem_bin in "$HOME"/.local/share/gem/ruby/*/bin; do
  [ -d "$init_gem_bin" ] && path_prepend "$init_gem_bin"
done
unset init_gem_bin

export PATH

if command -v batcat >/dev/null 2>&1; then
  alias bat='batcat'
fi
if command -v fdfind >/dev/null 2>&1; then
  alias fd='fdfind'
fi

alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias grep='grep --color=auto'
alias cls='clear'
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias ports='ss -tulpen'

unset -f path_prepend
