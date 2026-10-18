#!/bin/bash
# Small helper installed as /usr/local/bin/pisdbackup
set -e
SVC=pisdbackup.service
CFG=/etc/pisdbackup/config.json
USER_NAME="$(systemctl show -p User --value $SVC 2>/dev/null)"
HOME_DIR="$(getent passwd "${USER_NAME:-${USER:-$(id -un)}}" | cut -d: -f6)"
TOKEN_FILE="$HOME_DIR/.config/pisdbackup/web_token"
APP_DIR="$(systemctl show -p WorkingDirectory --value $SVC 2>/dev/null)"
PORT="$(python3 -c "import json,sys;print(json.load(open('$CFG')).get('web_port',5000))" 2>/dev/null || echo 5000)"

case "${1:-status}" in
  status)  systemctl status $SVC --no-pager -l | head -20
           echo; "$0" url ;;
  logs)    journalctl -u $SVC -f -n 100 ;;
  token)   cat "$TOKEN_FILE" 2>/dev/null || echo "no token yet (service not started, or web_auth=false)" ;;
  url)     IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
           TOK="$(cat "$TOKEN_FILE" 2>/dev/null || true)"
           echo "http://${IP:-<ip>}:${PORT}/${TOK:+?token=$TOK}"
           echo "http://$(hostname).local:${PORT}/${TOK:+?token=$TOK}" ;;
  restart|stop|start) sudo systemctl "$1" $SVC && systemctl is-active $SVC ;;
  update)  [ -n "$APP_DIR" ] || { echo "service not installed"; exit 1; }
           sudo -u "$USER_NAME" git -C "$APP_DIR" pull --ff-only
           sudo -u "$USER_NAME" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
           sudo systemctl restart $SVC && echo "updated and restarted" ;;
  config)  sudo "${EDITOR:-nano}" "$CFG" && sudo systemctl restart $SVC ;;
  *) echo "usage: pisdbackup {status|logs|token|url|restart|stop|start|update|config}"; exit 1 ;;
esac
