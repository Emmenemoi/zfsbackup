#!/usr/bin/python

#
#   Config file zfsbackup.conf should contain:
#
#[MAIN]
#sshkey_path = 
#ssh_user = 
#backup_server = 
#remote_zfs_dataset = 
#local_zfs_dataset = 
#
#[VMLIST]
#backups = <space separated xen machines>
#

import subprocess, time, re, ConfigParser, logging, sys, os, getopt, fcntl, logging
from localZfs import *
from remoteZfs import *

pid_file = '/var/run/zfslivebackup.pid'
logfile = "/var/log/zfsbackup/backup.log"
configfile = "./zfsbackup.conf"

silent = False
dryrun = False

class StreamToLogger(object):
   """
   Fake file-like stream object that redirects writes to a logger instance.
   """
   def __init__(self, logger, log_level=logging.INFO):
      self.logger = logger
      self.log_level = log_level
      self.linebuf = ''
 
   def write(self, buf):
      for line in buf.rstrip().splitlines():
         self.logger.log(self.log_level, line.rstrip())


def get_local_backup_vms():
   result = []

   cmd = "/usr/sbin/xm list"
   #output = commands.getoutput(cmd)
   output = subprocess.check_output(
        cmd,
        shell=True)

   for vm in output.splitlines():
      data = re.split('[\s]+', vm)
      uuid = data[1]
      name = data[0]
      if ( name in livebackups and  uuid != "ID" and uuid != 0 ) :
          result += [(uuid, name)]
   
   return result

def backup_vm( remoteZpool, vmhostname ):
    vmid = data = re.split('\.', vmhostname)[0]
    
    remoteDataset = remoteZpool.getDataset(remoteZpool.name + '/vm-' + vmid)
    localDataset = backup_vm.zpool.getDataset(backup_vm.zpool.name + '/vm-' + vmid)
    
    lastRemoteIncrementSnapshot = None
    lastLocalIncrementSnapshot = None
    if remoteDataset != None :
        lastRemoteIncrementSnapshot = remoteDataset.getLastBackupSnapshot()
        # do some cleaning if last run failed
        currentRemoteSnapshot = remoteDataset.getCurrentBackupSnapshot()
        if currentRemoteSnapshot != None:
            if not currentRemoteSnapshot.renameToLastBackup():
                sys.exit(2)

        if lastRemoteIncrementSnapshot == None and localDataset != None:
            lastRemoteIncrementSnapshot = remoteDataset.getMostRecentMatchingSnapshot( localDataset.snapshots )

    if localDataset != None:
         # do some cleaning if last failed
        currentLocalSnapshot = localDataset.getCurrentBackupSnapshot()
        if currentLocalSnapshot != None:
            if not currentLocalSnapshot.renameToLastBackup():
                sys.exit(2)

        lastLocalIncrementSnapshot = localDataset.getLastBackupSnapshot()
        # maybe we could find another old one 
        if lastLocalIncrementSnapshot == None and remoteDataset != None:
            lastLocalIncrementSnapshot = localDataset.getMostRecentMatchingSnapshot( remoteDataset.snapshots )
    else:
        logging.error("Impossible to find dataset %s" % localDataset.name)
    
    newsnapshot = localDataset.createBackupSnapshot()
    if lastLocalIncrementSnapshot != None and lastRemoteIncrementSnapshot != None:
        # incremental send possible
        success = remoteZpool.importSnapshot(remoteDataset, newsnapshot, lastLocalIncrementSnapshot)            
    else:
        # we create a new fresh send
        success = remoteZpool.importSnapshot(remoteDataset, newsnapshot)

    if success:
        #if lastLocalIncrementSnapshot != None:
        #    lastLocalIncrementSnapshot.destroy()
        newsnapshot.renameToLastBackup()
        remoteDataset = remoteZpool.getDataset(remoteZpool.name + '/vm-' + vmid)
        if remoteDataset != None:
            remoteDataset.rollBackupNames()
    else:
	logging.error("Cannot import: mmight need to clean old snapshots.")
	logging.error("=> zfs list -r -H -o name -t snapshot %s | xargs -n1 zfs release keep" % remoteDataset.name)
	logging.error("=> zfs destroy -rvd %s@%%" % remoteDataset.name)


# be sure runs only once
fp = open(pid_file, 'w')
try:
    fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    # another instance is running
    sys.exit(0)

try:
  opts, args = getopt.getopt( sys.argv[1:] ,"shd",["silent", "dry-run", "config-file="])
except getopt.GetoptError:
  print 'usage: -s or --silent / -d or --dry-run / --config-file=<path>'
  sys.exit(2)

for opt, arg in opts:
      if opt == '-h':
         print ' -s: silent'
         sys.exit()
      elif opt in ("-s", "--silent"):
         silent = True
      elif opt in ("-d", "--dry-run"):
         dryrun = True
      elif opt in ("--config-file"):
	configfile = arg

if (silent) :
    # verify arancloud log
    if not os.path.exists(os.path.dirname(logfile)):
        os.makedirs(os.path.dirname(logfile))
    logging.basicConfig(
       level=logging.DEBUG,
       format='%(asctime)s:%(levelname)s:%(name)s:%(message)s',
       filename=logfile,
       filemode='a'
    )

    stdout_logger = logging.getLogger('STDOUT')
    slo = StreamToLogger(stdout_logger, logging.INFO)
    sys.stdout = slo
     
    stderr_logger = logging.getLogger('STDERR')
    sle = StreamToLogger(stderr_logger, logging.ERROR)
    sys.stderr = sle
else:
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)

Config = ConfigParser.ConfigParser()
Config.read( configfile )
livebackups = re.split('[\s]+', Config.get("VMLIST", "backups") )
sshkey_path = Config.get("MAIN", "sshkey_path")
ssh_user = Config.get("MAIN", "ssh_user")
backup_server = Config.get("MAIN", "backup_server")
remote_zfs_dataset = Config.get("MAIN", "remote_zfs_dataset" )
local_zfs_dataset = Config.get("MAIN", "local_zfs_dataset" )

try:
    remoteZpool = RemoteZpool(backup_server, ssh_user, remote_zfs_dataset , dryrun, sshkey_path )
    backup_vm.zpool = Zpool(local_zfs_dataset, dryrun)

    for (uuid, name) in get_local_backup_vms():
       timestamp = time.strftime("%Y%m%d-%H:%M", time.gmtime())
       #print timestamp, uuid, name
       backup_vm( remoteZpool, name )
except ZFSError, e:
  print e
  sys.exit(2)


