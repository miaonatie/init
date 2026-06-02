# pwnnew: create a pwn challenge workspace from init templates.

pwnnew() {
  local root="${INIT_HOME:-}"
  if [ -z "$root" ]; then
    echo "pwnnew: INIT_HOME is not set. Run init-config.py from the package directory." >&2
    return 2
  fi

  if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "usage: pwnnew NAME [FILES...]"
    echo "       pwnnew FILE [MORE_FILES...]"
    echo "       pwnnew --no-extract ARCHIVE"
    return 0
  fi

  local tpl_dir="$root/config/templates"
  local name=""
  local files=()
  local auto_extract=1

  if [ "$#" -eq 0 ]; then
    pwnnew --help >&2
    return 2
  fi

  if [ "$1" = "--no-extract" ]; then
    auto_extract=0
    shift
  fi
  [ -n "$PWNNEW_NO_EXTRACT" ] && auto_extract=0

  if [ "$#" -eq 0 ]; then
    echo "pwnnew: missing name or file" >&2
    return 2
  fi

  if [ -f "$1" ]; then
    local first="$1"
    local base="$(basename "$first")"
    case "$base" in
      *.tar.gz|*.tar.xz|*.tar.bz2) name="${base%.*.*}" ;;
      *.tgz) name="${base%.tgz}" ;;
      *.txz) name="${base%.txz}" ;;
      *.zip|*.7z|*.rar|*.gz|*.xz|*.bz2) name="${base%.*}" ;;
      *) name="${base%.*}"; [ "$name" = "$base" ] && name="${base}_pwn" ;;
    esac
    files=("$@")
  else
    name="$1"
    shift
    files=("$@")
  fi

  name="${name:-chall_pwn}"
  local dir="$name"
  local i=1
  while [ -e "$dir" ]; do
    dir="${name}_${i}"
    i=$((i + 1))
  done
  mkdir -p "$dir" || return 1

  [ -f "$tpl_dir/payload.py" ] && cp -n "$tpl_dir/payload.py" "$dir/payload.py" && chmod +x "$dir/payload.py" 2>/dev/null || true
  [ -f "$tpl_dir/AGENTS.md" ] && cp -n "$tpl_dir/AGENTS.md" "$dir/AGENTS.md"

  local f
  for f in "${files[@]}"; do
    if [ -e "$f" ]; then
      cp -n "$f" "$dir/"
    else
      echo "warning: file not found: $f" >&2
    fi
  done

  if [ "$auto_extract" -eq 1 ]; then
    (
      cd "$dir" || exit 1
      local a
      for a in "${files[@]}"; do
        local b="$(basename "$a")"
        [ -f "$b" ] || continue
        case "$b" in
          *.tar.gz|*.tgz) tar -xzf "$b" ;;
          *.tar.xz|*.txz) tar -xJf "$b" ;;
          *.tar.bz2) tar -xjf "$b" ;;
          *.zip) command -v unzip >/dev/null 2>&1 && unzip -q "$b" ;;
          *.7z) command -v 7z >/dev/null 2>&1 && 7z x -y "$b" >/dev/null ;;
        esac
      done
    )
  fi

  cd "$dir" || return 1
  echo "workspace: $PWD"
  ls -la
}
