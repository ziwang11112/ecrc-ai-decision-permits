#!/usr/bin/env bash
# Trusted launcher. Usage: bash run_sandbox.sh INPUT_DIR FRESH_OUTPUT_DIR WORKER_PY [worker arguments...]
# No candidate runs until the explicitly supplied trusted worker reads /in.
# All candidate execution remains inside the fresh bwrap namespace and seccomp.
set -euo pipefail
if (( $# < 3 )); then
  printf 'Usage: run_sandbox.sh INPUT_DIR FRESH_OUTPUT_DIR TRUSTED_WORKER_PY [args...]\n' >&2
  exit 64
fi
launcher_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
input_dir="$(realpath -e -- "$1")"
output_dir="$(realpath -m -- "$2")"
worker_file="$(realpath -e -- "$3")"
shift 3
bwrap_bin='/mnt/d/AIR-014_ECRC_Paper_Clean_2026-08-16/research_pilots/recurring_software_repair_v1/baseline_v3/sandbox_tools/extracted/usr/bin/bwrap'
[[ -d "$input_dir" && -f "$worker_file" && ! -e "$output_dir" && ! -L "$output_dir" ]] || exit 65
[[ "$output_dir" != "$input_dir" && "$output_dir" != "$input_dir/"* ]] || exit 65
[[ -z "$(find "$input_dir" -type l -print -quit)" ]] || { printf 'Input symlinks rejected\n' >&2; exit 65; }
[[ -x "$bwrap_bin" && -x /usr/bin/prlimit && -x /usr/bin/timeout && -x /usr/bin/python3 ]] || exit 69
expected_bwrap='52231e1caf55bcbc667b269f49c63599a6f7db4767ae6a039580d0ff853db712'
actual_bwrap="$(sha256sum -- "$bwrap_bin")"
[[ "${actual_bwrap%% *}" == "$expected_bwrap" ]] || { printf 'bwrap hash mismatch\n' >&2; exit 69; }
# Only explicitly inventoried installed packages are exposed; no whole venv/home.
# Python stays -S, so .pth files and sitecustomize are not processed.
package_args=(--dir /opt --dir /opt/site-packages)
science_packages='/home/zwang/.venvs/memgen-repro-20260906/lib/python3.12/site-packages'
pytest_packages='/mnt/d/AIR-014_ECRC_Paper_Clean_2026-08-16/research_pilots/recurring_software_repair_v1/baseline_v3/sandbox_tools/deps'
for package in numpy numpy.libs numpy-2.3.5.dist-info sympy sympy-1.14.0.dist-info mpmath mpmath-1.3.0.dist-info dateutil python_dateutil-2.9.0.post0.dist-info six.py six-1.17.0.dist-info packaging packaging-26.3.dist-info; do
  [[ -e "$science_packages/$package" ]] || { printf 'Missing whitelisted dependency: %s\n' "$package" >&2; exit 69; }
  package_args+=(--ro-bind "$science_packages/$package" "/opt/site-packages/$package")
done
for package in pytest pytest-8.3.5.dist-info _pytest py.py pluggy pluggy-1.5.0.dist-info iniconfig iniconfig-2.1.0.dist-info; do
  [[ -e "$pytest_packages/$package" ]] || { printf 'Missing whitelisted dependency: %s\n' "$package" >&2; exit 69; }
  package_args+=(--ro-bind "$pytest_packages/$package" "/opt/site-packages/$package")
done
# Defaults are a proposed resource contract; the experiment must freeze them.
# AS bounds address space, not a cgroup RSS quota. Seccomp prevents descendants.
memory_bytes="${SANDBOX_MEMORY_BYTES:-536870912}"
wall_seconds="${SANDBOX_WALL_SECONDS:-30}"
cpu_seconds="${SANDBOX_CPU_SECONDS:-30}"
file_bytes="${SANDBOX_FILE_BYTES:-1048576}"
for numeric in "$memory_bytes" "$wall_seconds" "$cpu_seconds" "$file_bytes"; do
  [[ "$numeric" =~ ^[1-9][0-9]*$ ]] || exit 65
done
(( memory_bytes <= 1073741824 && wall_seconds <= 120 && cpu_seconds <= 120 && file_bytes <= 8388608 )) || exit 65
mkdir -p -- "$(dirname -- "$output_dir")"
mkdir -- "$output_dir"
set +e
/usr/bin/timeout --signal=TERM --kill-after=2 "$wall_seconds" \
  /usr/bin/prlimit --core=0:0 --nofile=64:64 \
  --as="$memory_bytes:$memory_bytes" --cpu="$cpu_seconds:$((cpu_seconds + 1))" \
  --fsize="$file_bytes:$file_bytes" -- \
  "$bwrap_bin" --unshare-all --unshare-user --uid 65534 --gid 65534 \
  --disable-userns --assert-userns-disabled --die-with-parent --new-session --cap-drop ALL \
  --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/bin /bin \
  "${package_args[@]}" \
  --proc /proc --dev /dev --size 33554432 --tmpfs /tmp \
  --dir /runner --ro-bind "$launcher_dir/sandbox_guard.py" /runner/sandbox_guard.py \
  --ro-bind "$launcher_dir/sandbox_bootstrap.py" /runner/sandbox_bootstrap.py \
  --ro-bind "$worker_file" /runner/worker.py --ro-bind "$input_dir" /in \
  --chdir /tmp --clearenv --setenv PATH /usr/bin --setenv HOME /tmp --setenv TMPDIR /tmp \
  --setenv LANG C.UTF-8 --setenv LC_ALL C.UTF-8 --setenv PYTHONDONTWRITEBYTECODE 1 \
  --setenv PYTHONUNBUFFERED 1 --setenv OMP_NUM_THREADS 1 --setenv OPENBLAS_NUM_THREADS 1 \
  --setenv MKL_NUM_THREADS 1 --setenv NUMEXPR_NUM_THREADS 1 \
  --remount-ro /proc --remount-ro /dev --remount-ro / \
  -- /usr/bin/python3 -I -S -B /runner/sandbox_bootstrap.py /runner/worker.py "$@" \
  </dev/null >"$output_dir/stdout.log" 2>"$output_dir/stderr.log"
return_code=$?
set -e
# Receipt is written by the trusted host launcher; the sandbox sees no /out bind.
printf '{"returncode":%d,"wall_limit_seconds":%s,"address_space_limit_bytes":%s,"per_log_file_limit_bytes":%s,"host_output_directory_mounted":false}\n' \
  "$return_code" "$wall_seconds" "$memory_bytes" "$file_bytes" >"$output_dir/launcher_receipt.json"
exit "$return_code"
