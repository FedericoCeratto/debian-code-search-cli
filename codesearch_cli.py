#!/usr/bin/env python

"""
CLI tool for Debian Code Search (https://codesearch.debian.net/)


"""


from argparse import ArgumentParser
from websocket import create_connection
import json
import requests
import sys
import time


WS_URL = "wss://codesearch.debian.net/instantws"
rate_limit = 1.0/20  # Rate-limit queries per second
PATHCOLOR = 33


def say(quiet, msg):
    """Print messages to stderr
    """
    if not quiet:
        sys.stderr.write("%s\n" % msg)


def fetch_json(path):
    """Fetch a JSON document from codesearch
    """
    r = requests.get("https://codesearch.debian.net/%s" % path)
    if r.ok:
        return r.json()

    if r.reason != 'Bad Gateway':
        say(False, "Fetch failure: %s" % r.reason)


def print_results(chunk, print_linenum, print_only_filenames, nocolor):
    """Print search results
    """
    pathline = "path: %s" % chunk['path']
    if nocolor:
        print(pathline)

    else:
        print("\033[%dm%s\033[0m" % (PATHCOLOR, pathline))

    if print_only_filenames:
        return

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
    """Run initial query on websocket
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
            say(False, "Unable to parse JSON document %s" % e)
            sys.exit(1)

        if u'Type' in chunk and chunk[u'Type'] == u'progress':
            # Progress update received
            if chunk[u'FilesTotal'] == chunk[u'FilesProcessed']:
                # The query has been completed
                ws.close()
                return chunk, printed_chunks

        elif 'package' in chunk:
            print_results(chunk, args.linenumber, args.print_filenames, args.nocolor)
            printed_chunks.add((chunk['path'], chunk['line']))



def parse_args():
    ap = ArgumentParser()
    ap.add_argument('searchstring')
    ap.add_argument('--max-pages', type=int, default=20)
    ap.add_argument('-q', '--quiet', action='store_true')
    ap.add_argument('-l', '--linenumber', action='store_true')
    ap.add_argument('--nocolor', action='store_true',
                    help="Do not colorize output")
    ap.add_argument('-n', '--print-filenames', action='store_true',
                    help='Print only matching filenames, no contents')
    args = ap.parse_args()
    if not sys.stdout.isatty():
        args.nocolor = True

    return args


def fetch_json_pages(query_id, printed_chunks, args):
    """Fetch JSONs page and print the results
    """
    for page_num in xrange(0, args.max_pages):
        page = fetch_json("results/%s/page_%d.json" % (query_id, page_num))
        if page is None:
            break

        printed = False
        for chunk in page:
            if (chunk['path'], chunk['line']) not in printed_chunks:
                print_results(chunk, args.linenumber, args.print_filenames, args.nocolor)
                printed = True

        if sys.stdout.isatty():
            # Implement pagination (only if at least one chunk was printed)
            if printed:
                print("----- Press Enter to continue or Ctrl-C to exit -----")
                raw_input()

        else:
            # The output is being piped somewhere: go through all the pages
            time.sleep(rate_limit)


def main():
    args = parse_args()

    # Execute query over a websocket
    last_ws_chunk, printed_chunks = run_websocket_query(args)
    query_id = last_ws_chunk['QueryId']

    fetch_json_pages(query_id, printed_chunks, args)

    say(args.quiet, "--\nFiles grepped: %d" % last_ws_chunk['FilesTotal'])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit()
