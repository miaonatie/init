# Managed by init. Edit the repository copy, then rerun: python3 init.py

path_prepend() {
  [ -n "$1" ] || return 0
  case ":$PATH:" in
    *":$1:"*) ;;
    *) PATH="$1:$PATH" ;;
  esac
}

path_prepend "$HOME/.local/bin"

# Ruby --user-install binaries.
for init_gem_bin in "$HOME"/.local/share/gem/ruby/*/bin; do
  [ -d "$init_gem_bin" ] && path_prepend "$init_gem_bin"
done
unset init_gem_bin

export PATH

unset -f path_prepend
