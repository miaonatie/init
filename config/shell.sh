# init shell configuration
# Sourced by ~/.bashrc and ~/.zshrc through init-config.py.
# Edit this file directly; reopen your terminal or run: source ~/.bashrc / source ~/.zshrc

# PATH helper. Adds a directory once, at the front, when it exists or may be created later.
path_prepend() {
  [ -n "$1" ] || return 0
  case ":$PATH:" in
    *":$1:"*) ;;
    *) PATH="$1:$PATH" ;;
  esac
}

# User-level tools installed by pip --user, cargo, Go, pnpm, Claude/Codex wrappers, etc.
# nvm itself is loaded by nvm's installer-generated shell block, not here, to avoid double loading.
path_prepend "$HOME/.local/bin"
path_prepend "$HOME/.cargo/bin"
path_prepend "$HOME/.local/go/bin"
path_prepend "$HOME/go/bin"
export PATH

# zsh + oh-my-zsh. Skip if oh-my-zsh is already loaded by the user's .zshrc.
if [ -n "$ZSH_VERSION" ] && [ -d "$HOME/.oh-my-zsh" ] && ! type omz >/dev/null 2>&1; then
  export ZSH="${ZSH:-$HOME/.oh-my-zsh}"
  ZSH_THEME="${ZSH_THEME:-cradle}"
  plugins=(git zsh-autosuggestions zsh-syntax-highlighting z extract web-search)
  [ -s "$ZSH/oh-my-zsh.sh" ] && source "$ZSH/oh-my-zsh.sh"
fi

# Modern ls shortcuts with graceful fallback.
if command -v eza >/dev/null 2>&1; then
  alias ll='eza -alh --group-directories-first --git'
  alias la='eza -a --group-directories-first'
  alias l='eza -lh --group-directories-first'
elif command -v exa >/dev/null 2>&1; then
  alias ll='exa -alh --group-directories-first --git'
  alias la='exa -a --group-directories-first'
  alias l='exa -lh --group-directories-first'
else
  alias ll='ls -alF'
  alias la='ls -A'
  alias l='ls -CF'
fi

command -v batcat >/dev/null 2>&1 && alias bat='batcat'
command -v fdfind >/dev/null 2>&1 && alias fd='fdfind'

alias grep='grep --color=auto'
alias cls='clear'
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias df='df -h'
alias du='du -h'
alias free='free -h'
alias ports='ss -tulpen'
alias path='printf "%s\n" ${PATH//:/ }'

# trashy: crate is trashy, executable is trash.
if command -v trash >/dev/null 2>&1; then
  alias tp='trash put'
  alias tl='trash list'
  alias tr='trash restore'
  alias te='trash empty'
fi

unset -f path_prepend
