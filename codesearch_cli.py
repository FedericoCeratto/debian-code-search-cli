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
import collections

# result lines have HTML-escaped entities, so prepare an unescaper
if (sys.version_info > (3, 0)):
    import html.parser as HTMLParser
else:
    import HTMLParser
unescape = HTMLParser.HTMLParser().unescape

WS_URL = "wss://codesearch.debian.net/instantws"
rate_limit = 1.0/20  # Rate-limit queries per second
PATHCOLOR = 33
DUPE_PATHCOLOR = 36

dedupe_results = []


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
        
        
def is_excluded(chunk, exclusions):
    if exclusions and 'path' in chunk:
        for exclude in exclusions:
            if exclude in chunk['path']:
                return True


def get_result_body(chunk, print_linenum, nocolor):
    body = ""
    for item in ('ctxp2', 'ctxp1', 'context', 'ctxn1', 'ctxn2'):
        line = chunk[item]
        line = line.encode('utf-8')
        line = unescape(line)
        if print_linenum:
            if item == 'context':
                body += "%7d %s\n" % (chunk['line'], line)

            else:
                body += "        %s\n" % line

        else:
            body += "%s\n" % line

    return body[:-1] # trim trailing line


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

    print(get_result_body(chunk, print_linenum, nocolor))


def print_dedupe(print_linenum, print_only_filenames, nocolor):
    """amalgamate duplicate results and print summary
    """

    bodies = collections.defaultdict(list)
    for chunk in dedupe_results:
        body = get_result_body(chunk, print_linenum, nocolor)
        bodies[body].append(chunk)

    for body, chunks in bodies.items():
        print_results(chunks[0], print_linenum, print_only_filenames, nocolor)

        first_path = chunks[0]['path']
        for chunk in chunks[1:]:
            pathline = "also: %s" % chunk['path']
            if nocolor:
                print(pathline)

            else:
                for common_suffix in range(1, len(pathline)):
                    if pathline[-common_suffix:] != first_path[-common_suffix:]:
                        break

                print("\033[%dm%s\033[%dm%s\033[0m" % (PATHCOLOR, pathline[:-common_suffix+1],
                    DUPE_PATHCOLOR, pathline[-common_suffix+1:]))
        else:
            print("")


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
            
        if is_excluded(chunk, args.exclude):
            continue
           
        if u'Type' in chunk and chunk[u'Type'] == u'progress':
            # Progress update received
            if chunk[u'FilesTotal'] == chunk[u'FilesProcessed']:
                # The query has been completed
                ws.close()
                return chunk, printed_chunks

        elif 'package' in chunk:
            if args.dedupe:
                dedupe_results.append(chunk)

            else:
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
    ap.add_argument('-d', '--dedupe', action='store_true',
                    help='amalgamate results for the same file in different packages')
    ap.add_argument('-x', '--exclude', action='append',
                    help='list of path fragments to exclude from results')
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
            if is_excluded(chunk, args.exclude):
                continue
            
            if (chunk['path'], chunk['line']) not in printed_chunks:
                if args.dedupe:
                    dedupe_results.append(chunk)
                else:
                    print_results(chunk, args.linenumber, args.print_filenames, args.nocolor)
                printed = True

        if not args.dedupe and sys.stdout.isatty():
            # Implement pagination (only if at least one chunk was printed)
            if printed and page_num != args.max_pages - 1:
                print("----- Press Enter to continue or Ctrl-C to exit -----")
                raw_input()

        else:
            # The output is being piped somewhere: go through all the pages
            time.sleep(rate_limit)


def main():
    args = parse_args()

    if args.quiet:
        requests.packages.urllib3.disable_warnings()

    # Execute query over a websocket
    last_ws_chunk, printed_chunks = run_websocket_query(args)
    query_id = last_ws_chunk['QueryId']

    fetch_json_pages(query_id, printed_chunks, args)

    if args.dedupe:
        print_dedupe(args.linenumber, args.print_filenames, args.nocolor)

    say(args.quiet, "--\nFiles grepped: %d" % last_ws_chunk['FilesTotal'])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("")
        sys.exit()
