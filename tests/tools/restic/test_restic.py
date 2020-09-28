from jumpscale.loader import j
from jumpscale.core.exceptions import NotFound, Runtime
from unittest import TestCase

import random
import tempfile
import uuid
import os
import shutil
import socket
import subprocess


class TempDir(tempfile.TemporaryDirectory):
    def clear_contents(self):
        """Keep the directory but remove its contents"""
        dir_name = self.name
        for filename in os.listdir(dir_name):
            file_path = os.path.join(dir_name, filename)
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)


class TestRestic(TestCase):
    @classmethod
    def setUpClass(cls):
        if subprocess.call(["which", "restic"], stdout=subprocess.DEVNULL):
            raise NotFound(f"restic not installed")

    def setUp(self):
        """Initialize a repo and change current directory to a newly created temp directory"""
        self.temps = []
        self.repos_temp_dir = self._create_temp_dir()
        os.chdir(self.repos_temp_dir.name)
        self.instance_name = j.data.random_names.random_name()
        self.password = "123"
        self.instance = j.tools.restic.new(self.instance_name, password=self.password, repo=self.instance_name)
        self.instance.init_repo()

    def _create_temp_dir(self):
        """Return a new temp directory"""
        temp_dir = TempDir()
        self.temps.append(temp_dir)
        return temp_dir

    def _create_random_dir(self, n=21):
        """Create a directory with n items

        Args:
            n (int, optional): The number of nested items (files and directories)

        Returns:
            TempDir: The created temp directory
        """
        d = self._create_temp_dir()
        d_dict = self._create_random_dir_dict()
        self._fill_dir(d.name, d_dict)
        return d

    def _random_name(self):
        """Return a random name"""
        return str(uuid.uuid4())

    def _random_content(self):
        """Return a random string with length between 10 and 100"""
        length = random.randint(10, 100)
        res = ""
        for _ in range(length):
            res += chr(random.randint(97, 123))
        return res

    def _generate_random_tree(self, n):
        """Generate a random rooted directed tree to be used as a representation for a directory

        Args:
            n (int, optional): The number of nested items (files and directories)

        Returns:
            TempDir: The adjacency list of the tree
        """
        adjacency_list = [[] for i in range(n)]
        for i in range(1, n):
            parent = random.randint(0, i - 1)
            adjacency_list[parent].append(i)
        return adjacency_list

    def _get_file_object(self, node, adjacency_list):
        """Return a dict if the node represents a dir, otherwise it returns a string with the file content

        Args:
            node (int): The node to be processed in the tree
            adjacency_list (list[list]): The adjacency list of the tree

        Returns:
            (dict | string)
        """
        if len(adjacency_list[node]) == 0:
            return self._random_content()
        res = {}
        for i in adjacency_list[node]:
            res[self._random_name()] = self._get_file_object(i, adjacency_list)
        return res

    def _create_random_dir_dict(self, n=21):
        """Create a directory dict with n items

        Args:
            n (int, optional): The number of nested items (files and directories)

        Returns:
            TempDir: The created temp directory
        """
        tree = self._generate_random_tree(n)
        return self._get_file_object(0, tree)

    def _fill_dir(self, dir_name, dir_dict):
        """Fill the directory at the given path with directory dict

        Args:
            dir_name  (str): The path of the directory
            dir_dict (dict): The dict representation of the directory
        """
        for k, v in dir_dict.items():
            if isinstance(v, dict):
                self._fill_dir(os.path.join(dir_name, k), v)
            else:
                os.makedirs(dir_name, exist_ok=True)
                file_path = os.path.join(dir_name, k)
                with open(file_path, "w") as f:
                    f.write(v)

    def _canonicalize(self, path):
        """Return a cononical form of the directory, used for comparison

        Args:
            path (str): The directory path
        """
        res = {}  # path: content
        for root, _, files in os.walk(path, topdown=True):
            for f in files:
                file_path = os.path.join(root, f)
                res[file_path[len(path) :]] = j.sals.fs.read_file(file_path)
        return res

    def _check_dirs_equal(self, first_dir, second_dir):
        """Check if the two directories have the same content

        Args:
            first_dir (str): The first directory path
            second_dir (str): The second directory path
        """
        return self._canonicalize(first_dir) == self._canonicalize(second_dir)

    def test_backup_restore(self):
        """Test case for simple directory backup and restore
        **Test Scenario**
        #. Create a directory with random content
        #. Create another empty directory to restore the backup in it
        #. Use restic to back it up
        #. Use restic to restore it to the backup directory
        #. Check that the restored content and the original are the same
        """
        dir_dict = self._create_random_dir_dict()
        original_dir = self._create_temp_dir()
        backup_dir = self._create_temp_dir()
        self._fill_dir(original_dir.name, dir_dict)
        self.instance.backup(original_dir.name, tags=["tag1", "tag2"])
        self.instance.restore(backup_dir.name, path=original_dir.name)
        restore_path = os.path.join(backup_dir.name, original_dir.name[1:])
        self.assertTrue(self._check_dirs_equal(original_dir.name, restore_path))

    def test_multiple_restores(self):
        """Test case for directory backup and restore with modifications
        **Test Scenario**
        #. Create a directory with random content
        #. Create another directory with random content
        #. Use restic to make a backup of the first directory
        #. Change the contents of the first directory
        #. Make another backup of the first directory
        #. Backup the new version of the first directory
        #. Check that the backup and the new version are the same
        #. Backup the old version of the first directory
        #. Check that the backup and the old version are the same
        #. Restore the latest backup using host name
        #. Check that the backup and the new version are the same
        """
        first_dir_dict = self._create_random_dir_dict()
        second_dir_dict = self._create_random_dir_dict()
        original_dir = self._create_temp_dir()
        first_dir_copy = self._create_temp_dir()
        backup_dir = self._create_temp_dir()
        self._fill_dir(original_dir.name, first_dir_dict)
        self.instance.backup(original_dir.name, tags=["tag1", "tag2"])
        j.sals.fs.copy_tree(original_dir.name, first_dir_copy.name)
        original_dir.clear_contents()
        self._fill_dir(original_dir.name, second_dir_dict)
        self.instance.backup(original_dir.name, tags=["tag3", "tag4"])

        snapshots = self.instance.list_snapshots()
        self.instance.restore(backup_dir.name, snapshot_id=snapshots[1]["id"])
        restore_path = os.path.join(backup_dir.name, original_dir.name[1:])
        self.assertTrue(self._check_dirs_equal(original_dir.name, restore_path))

        backup_dir.clear_contents()
        restore_path = os.path.join(backup_dir.name, original_dir.name[1:])
        self.instance.restore(backup_dir.name, snapshot_id=snapshots[0]["id"])
        self.assertTrue(self._check_dirs_equal(first_dir_copy.name, restore_path))

        backup_dir.clear_contents()
        restore_path = os.path.join(backup_dir.name, original_dir.name[1:])
        self.instance.restore(backup_dir.name, host=socket.gethostname())
        self.assertTrue(self._check_dirs_equal(original_dir.name, restore_path))

    def test_snapshot_listing(self):
        """Test case for snapshots listing
        **Test Scenario**
        #. Make two directories with random content
        #. Backup the first then the second then the third with tags: [tag1, tag2], [tag2, tag3], [tag2, tag3]
        #. List the snapshots using the tag name [(tag1), (tag2), (tag3), (tag1, tag3)]
        #. Check that any snapshot that had a tag that was passed is included in the result
        #. Check listing with the path
        """
        first_dir = self._create_random_dir()
        second_dir = self._create_random_dir()
        self.instance.backup(first_dir.name, tags=["tag1", "tag2"])
        self.instance.backup(second_dir.name, tags=["tag2", "tag3"])
        self.instance.backup(first_dir.name, tags=["tag2", "tag3"])
        snapshots = self.instance.list_snapshots()
        tag1_snapshot = self.instance.list_snapshots(tags=["tag1"])
        tag2_snapshot = self.instance.list_snapshots(tags=["tag2"])
        tag3_snapshot = self.instance.list_snapshots(tags=["tag3"])
        tag13_snapshot = self.instance.list_snapshots(tags=["tag1", "tag3"])
        latest_tag2_snapshots = self.instance.list_snapshots(tags=["tag2"], last=True)
        working_dir_snapshots = self.instance.list_snapshots(path=first_dir.name)
        self.assertEqual(len(tag1_snapshot), 1)
        self.assertEqual(len(tag2_snapshot), 3)
        self.assertEqual(len(tag3_snapshot), 2)
        self.assertEqual(len(tag13_snapshot), 3)
        self.assertEqual(tag1_snapshot[0]["id"], snapshots[0]["id"])
        self.assertEqual(tag2_snapshot[0]["id"], snapshots[0]["id"])
        self.assertEqual(tag2_snapshot[1]["id"], snapshots[1]["id"])
        self.assertEqual(tag3_snapshot[0]["id"], snapshots[1]["id"])
        self.assertEqual(latest_tag2_snapshots[0]["id"], snapshots[1]["id"])
        self.assertEqual(latest_tag2_snapshots[1]["id"], snapshots[2]["id"])
        self.assertEqual(working_dir_snapshots[0]["id"], snapshots[0]["id"])

    def test_autobackup(self):
        """Test case for auto backup
        **Test Scenario**
        #. Make a directory with random content
        #. Check that there's no backup running
        #. Turn on auto backup and check it's turned on
        #. Turn it off and check it's off
        """
        working_dir = self._create_random_dir()
        self.assertFalse(self.instance.auto_backup_running(working_dir.name))
        self.instance.auto_backup(working_dir.name)
        self.assertTrue(self.instance.auto_backup_running(working_dir.name))
        self.instance.disable_auto_backup(working_dir.name)
        self.assertFalse(self.instance.auto_backup_running(working_dir.name))

    def test_remove_snapshots(self):
        """Test case for snapshot removal
        **Test Scenario**
        #. Create multiple snapshots
        #. Check all of them are created
        #. Remove all but the last one
        #. Check only one snapshot remains
        """
        working_dir = self._create_random_dir()
        self.instance.backup(working_dir.name)
        self.instance.backup(working_dir.name)
        self.instance.backup(working_dir.name)
        self.assertEqual(len(self.instance.list_snapshots()), 3)
        self.instance.forget(keep_last=1, prune=True)
        self.assertEqual(len(self.instance.list_snapshots()), 1)

    def test_raises(self):
        """Test case for unusual inputs
        **Test Scenario**
        #. Call restore without passing it any info
        #. Restore a directory that wasn't backed up
        """
        with self.assertRaises(ValueError):
            self.instance.restore("/tmp/123", latest=False)
        with self.assertRaises(Runtime):
            self.instance.restore("/tmp/123", path="sadf")

    def tearDown(self):
        """Clean up all created temp directories and removes the restic instance"""
        self.instance.forget(keep_last=0)
        j.tools.restic.delete(self.instance_name)
        for temp_dir in self.temps:
            temp_dir.cleanup()
