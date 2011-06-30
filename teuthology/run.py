import argparse
import os
import yaml
import getpass
import socket

def config_file(string):
    config = {}
    try:
        with file(string) as f:
            g = yaml.safe_load_all(f)
            for new in g:
                config.update(new)
    except IOError, e:
        raise argparse.ArgumentTypeError(str(e))
    return config

class MergeConfig(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        config = getattr(namespace, self.dest)
        for new in values:
            config.update(new)

def parse_args():
    parser = argparse.ArgumentParser(description='Run ceph integration tests')
    parser.add_argument(
        '-v', '--verbose',
        action='store_true', default=None,
        help='be more verbose',
        )
    parser.add_argument(
        'config',
        metavar='CONFFILE',
        nargs='+',
        type=config_file,
        action=MergeConfig,
        default={},
        help='config file to read',
        )
    parser.add_argument(
        '--archive',
        metavar='DIR',
        help='path to archive results in',
        )
    parser.add_argument(
        '--description',
        help='job description'
        )
    parser.add_argument(
        '--owner',
        help='job owner'
        )

    args = parser.parse_args()
    return args

def main():
    from gevent import monkey; monkey.patch_all()
    from orchestra import monkey; monkey.patch_all()

    import logging

    log = logging.getLogger(__name__)
    ctx = parse_args()

    loglevel = logging.INFO
    if ctx.verbose:
        loglevel = logging.DEBUG

    logging.basicConfig(
        level=loglevel,
        )

    if ctx.archive is not None:
        os.mkdir(ctx.archive)

        handler = logging.FileHandler(
            filename=os.path.join(ctx.archive, 'teuthology.log'),
            )
        formatter = logging.Formatter(
            fmt='%(asctime)s.%(msecs)03d %(levelname)s:%(name)s:%(message)s',
            datefmt='%Y-%m-%dT%H:%M:%S',
            )
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)


        with file(os.path.join(ctx.archive, 'config.yaml'), 'w') as f:
            yaml.safe_dump(ctx.config, f, default_flow_style=False)

    log.debug('\n  '.join(['Config:', ] + yaml.safe_dump(ctx.config, default_flow_style=False).splitlines()))
    log.info('Opening connections...')

    from orchestra import connection, remote
    import orchestra.cluster

    remotes = [remote.Remote(name=t, ssh=connection.connect(t))
               for t in ctx.config['targets']]
    ctx.cluster = orchestra.cluster.Cluster()
    for rem, roles in zip(remotes, ctx.config['roles']):
        ctx.cluster.add(rem, roles)

    ctx.summary = {}

    if ctx.owner is not None:
        ctx.summary['owner'] = ctx.owner
    else:
        ctx.summary['owner'] = getpass.getuser() + '@' + socket.gethostname()

    if ctx.description is not None:
        ctx.summary['description'] = ctx.description

    for task in ctx.config['tasks']:
        assert 'kernel' not in task, \
            'kernel installation shouldn be a base-level item, not part of the tasks list'

    init_tasks = [{'internal.check_conflict': None}]
    if 'kernel' in ctx.config:
        init_tasks.append({'kernel': ctx.config['kernel']})
    init_tasks.extend([
            {'internal.base': None},
            {'internal.archive': None},
            {'internal.coredump': None},
            {'internal.syslog': None},
            ])

    ctx.config['tasks'][:0] = init_tasks

    from teuthology.run_tasks import run_tasks
    try:
        run_tasks(tasks=ctx.config['tasks'], ctx=ctx)
    finally:
        if ctx.archive is not None:
            with file(os.path.join(ctx.archive, 'summary.yaml'), 'w') as f:
                yaml.safe_dump(ctx.summary, f, default_flow_style=False)


def nuke():
    from gevent import monkey; monkey.patch_all()
    from orchestra import monkey; monkey.patch_all()

    import logging

    log = logging.getLogger(__name__)
    ctx = parse_args()

    loglevel = logging.INFO
    if ctx.verbose:
        loglevel = logging.DEBUG

    logging.basicConfig(
        level=loglevel,
        )

    log.info('\n  '.join(['targets:', ] + yaml.safe_dump(ctx.config['targets'], default_flow_style=False).splitlines()))
    log.info('Opening connections...')

    from orchestra import connection, remote, run
    import orchestra.cluster

    remotes = [remote.Remote(name=t, ssh=connection.connect(t))
               for t in ctx.config['targets']]
    ctx.cluster = orchestra.cluster.Cluster()

    for rem, name in zip(remotes, ctx.config['targets']):
        ctx.cluster.add(rem, name)

    log.info('Killing daemons, unmounting, and removing data...')

    ctx.cluster.run(
        args=[
            'killall',
            '--quiet',
            '/tmp/cephtest/binary/usr/local/bin/cmon',
            '/tmp/cephtest/binary/usr/local/bin/cosd',
            '/tmp/cephtest/binary/usr/local/bin/cmds',
            '/tmp/cephtest/binary/usr/local/bin/cfuse',
            run.Raw(';'),
            'fusermount', '-u', '/tmp/cephtest/mnt.*',
            run.Raw(';'),
            'rm', '-rf', '/tmp/cephtest'
            ])

    log.info('Done.')
