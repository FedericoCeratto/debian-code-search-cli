#!/usr/bin/env python2

"""
Debian Code Search http://codesearch.debian.net/

CLI search tool

"""
from argparse import ArgumentParser
from websocket import create_connection
import requests
import json
import sys
import time


WS_URL = "ws://codesearch.debian.net/instantws"
rate_limit = 1.0/20  # Rate-limit queries per second


def say(quiet, msg):
    """Print messages to stderr
    """
    if not quiet:
        sys.stderr.write("%s\n" % msg)


def fetch_json(path):
    """Fetch a JSON document from codesearch
    """
    r = requests.get("http://codesearch.debian.net/%s" % path)
    if r.ok:
        return r.json()

    if r.reason != 'Bad Gateway':
        say(False, "Fetch failure: %s" % r.reason)


def print_results(chunk, print_linenum):
    """Print search results
    """
    print('path ' + chunk['path'])
    for item in ('ctxp2', 'ctxp1', 'context', 'ctxn1', 'ctxn2'):
        line = chunk[item]
        line = line.encode('utf-8')
        if print_linenum:
            if item == 'context':
                print("%7d %s" % (chunk['line'], line))
            else:
                print("        %s" % line)

        else:
            print(line)


def run_websocket_query(args):
    """Run query on websocket
    """

    printed_chunks = set()
    ws = create_connection(WS_URL)

    query = {'Query': "q=%s" % args.searchstring}
    query = json.dumps(query)
    say(args.quiet, 'Sending query...')
    ws.send(query)

    while True:
        chunk = ws.recv()
        try:
            chunk = json.loads(chunk)
        except Exception as e:
            say(False, e)
            sys.exit(1)

        if 'package' in chunk:
            print_results(chunk, args.linenumber)
            printed_chunks.add((chunk['path'], chunk['line']))

        elif 'FilesTotal' in chunk:
            ws.close()
            return chunk, printed_chunks


def main():
    ap = ArgumentParser()
    ap.add_argument('searchstring')
    ap.add_argument('--max-pages', type=int, default=20)
    ap.add_argument('-q', '--quiet', action='store_true')
    ap.add_argument('-l', '--linenumber', action='store_true')
    args = ap.parse_args()

    last_ws_chunk, printed_chunks = run_websocket_query(args)
    query_id = last_ws_chunk['QueryId']

    for page_num in xrange(0, args.max_pages):
        page = fetch_json("results/%s/page_%d.json" % (query_id, page_num))
        if page is None:
            break

        for p in page:
            if (p['path'], p['line']) not in printed_chunks:
                printed_chunks.add((p['path'], p['line']))
                print_results(p, args.linenumber)

        if sys.stdout.isatty():
            print("----- Press Enter to continue or Ctrl-C to exit -----")
            raw_input()

        else:  # the output is being piped somewhere: go through all the pages
            time.sleep(rate_limit)

    say(args.quiet, "--\nFiles grepped: %d" % last_ws_chunk['FilesTotal'])
    if len(printed_chunks) != last_ws_chunk['Results']:
        say(args.quiet, "Results: %d" % last_ws_chunk['Results'])
        say(args.quiet, "Printed: %d" % len(printed_chunks))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit()
