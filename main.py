# -*- coding: utf-8 -*-
from flask import Flask, request
from datetime import datetime
import logging
import json
import os
import time
import requests
import jwt
import re

gh_priv_key = os.environ['GH_PRIV_KEY']
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('checktodo')

app = Flask(__name__)


def checktodo_main():
    req = request.get_json()
    try:
        action = req.get('action')

        if (action != 'synchronize' and action != 'opened'
                and action != 'rerequested'):
            logger.info(f'Ignored action {action} with data {req}')
            return 'ok'

        if action == 'rerequested':
            assert len(req['check_run']['check_suite']['pull_requests']) == 1
            pull_request = req['check_run']['check_suite']['pull_requests'][0]
        else:
            pull_request = req.get('pull_request')

        if pull_request is None:
            logger.warning(f'No \'pull_request\' for action {action}!')
            return 'ok'

        now = int(time.time())
        check = {
            'iat': now,
            'exp': now + 600,
            'iss': '16283'
        }

        jwt_token = jwt.encode(check, gh_priv_key, algorithm='RS256').decode(
            'utf-8')
        installation_id = req['installation']['id']

        # Get a token.
        r = requests.post(
            f'https://api.github.com/app/installations'
            f'/{installation_id}/access_tokens',
            headers={
                'Authorization': f'Bearer {jwt_token}',
                'Accept': 'application/vnd.github.machine-man-preview+json'
            })

        token = json.loads(r.text)['token']
        # Should be of the format:
        # https://api.github.com/repos/judepereira/platform-engine
        base_url = pull_request['base']['repo']['url']
        repo_full_name = req["repository"]["full_name"]
        diff_url = f'https://github.com' \
                   f'/{repo_full_name}' \
                   f'/pull/{pull_request["number"]}.diff'

        r = requests.get(diff_url)
        lines = r.text.split('\n')
        current_file = None
        current_pos = 0
        added = []
        for line in lines:
            if current_pos is not None:
                current_pos = current_pos + 1

            if line.startswith('+++'):
                current_file = line[6:]
                current_pos = None
                continue
            elif line.startswith('@@'):
                current_pos = int(line.split(' ')[2].split(',')[0]) - 1
            elif current_file is not None \
                    and current_pos is not None \
                    and line.startswith('+'):
                if re.match(r'([^\w\d]|^)todo(?![\w\d])', line.lower()):
                    added.append({
                        'line': current_pos,
                        'file': current_file,
                        'content': line[1:80]
                    })
            # current_pos = current_pos + 1

        pr_head_sha = pull_request['head']['sha']
        check = {
            'name': 'No added/edited TODO items found',
            'head_sha': pr_head_sha,
            'status': 'completed',
            'completed_at': f'{datetime.now().isoformat()[:19]}Z'
        }

        if len(added) > 0:
            check['conclusion'] = 'failure'
            check['name'] = 'Added/edited TODO items found'

            text = 'Added/edited TODO items found:\n'
            for e in added:
                # text = f'{text}https://github.com' \
                #        f'/{repo_full_name}' \
                #        f'/blob/{pr_head_sha}' \
                #        f'/{e["file"]}#L{e["line"]}\n'

                file_url = f'https://github.com/{repo_full_name}' \
                           f'/blob/{pr_head_sha}' \
                           f'/{e["file"]}#L{e["line"]}'

                this_line = f'[{e["file"]}#L{e["line"]}]({file_url}): ' \
                            f'`{e["content"]}`'

                # Append to the existing.
                text = f'{text} - {this_line}\n'

            output = {
                'title': 'Check TODO',
                'summary': f'{len(added)} added/edited TODO '
                           f'item(s) were found',
                'text': text
            }
            check['output'] = output
        else:
            check['conclusion'] = 'success'

        check_kwargs = {
            'url': f'{base_url}/check-runs',
            'data': json.dumps(check),
            'headers': {
                'Accept': 'application/vnd.github.antiope-preview+json',
                'Authorization': f'token {token}',
                'Content-Type': 'application/json; charset=utf-8'
            }
        }

        if action == 'rerequested' and req.get('check-run'):
            check_kwargs['url'] = f'{base_url}/check-runs/' \
                                  f'{req["check-run"]["id"]}'
            r = requests.patch(**check_kwargs)
        else:
            r = requests.post(**check_kwargs)

        if int(r.status_code / 100) == 2:
            logger.info(f'Payload processed: {req}')
            logger.info(f'Successfully processed action {action} for '
                        f'{req["repository"]["full_name"]}:'
                        f' {len(added)} todos')
        else:
            logger.warning(f'FAILED: status: {r.status_code}; '
                           f'response: {r.text}; error: {r.reason}; '
                           f'payload = {req}')

        return 'ok'
    except:
        logger.exception(f'Failed to process {req}')
        return 'ok'


if __name__ == "__main__":
    app.run(port=8000, host='0.0.0.0')
