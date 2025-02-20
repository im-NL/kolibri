import os
import platform
import sys
import uuid
from collections import namedtuple
from datetime import timedelta

import mock
from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from mock import patch
from morango.constants import transfer_statuses
from morango.models import DatabaseIDModel
from morango.models import InstanceIDModel
from morango.models import SyncSession
from morango.models import TransferSession
from rest_framework import status
from rest_framework.test import APITestCase

import kolibri
from kolibri.core.auth.constants.role_kinds import ADMIN
from kolibri.core.auth.models import Facility
from kolibri.core.auth.models import FacilityDataset
from kolibri.core.auth.models import FacilityUser
from kolibri.core.auth.models import Role
from kolibri.core.auth.test.helpers import clear_process_cache
from kolibri.core.auth.test.helpers import create_superuser
from kolibri.core.auth.test.helpers import provision_device
from kolibri.core.auth.test.test_api import ClassroomFactory
from kolibri.core.auth.test.test_api import FacilityFactory
from kolibri.core.auth.test.test_api import FacilityUserFactory
from kolibri.core.content.models import ContentDownloadRequest
from kolibri.core.content.models import ContentRemovalRequest
from kolibri.core.content.models import ContentRequestReason
from kolibri.core.device.models import DevicePermissions
from kolibri.core.device.models import DeviceSettings
from kolibri.core.device.models import DeviceStatus
from kolibri.core.device.models import LearnerDeviceStatus
from kolibri.core.device.models import StatusSentiment
from kolibri.core.device.models import UserSyncStatus
from kolibri.core.public.constants import user_sync_statuses
from kolibri.core.public.constants.user_sync_options import DELAYED_SYNC
from kolibri.plugins.app.test.helpers import register_capabilities
from kolibri.plugins.app.utils import GET_OS_USER
from kolibri.plugins.app.utils import interface
from kolibri.plugins.utils.test.helpers import plugin_disabled
from kolibri.plugins.utils.test.helpers import plugin_enabled
from kolibri.utils.tests.helpers import override_option


DUMMY_PASSWORD = "password"


class DeviceProvisionTestCase(APITestCase):
    def setUp(self):
        clear_process_cache()

    superuser_data = {"username": "superuser", "password": "password"}
    facility_data = {"name": "Wilson Elementary"}
    preset_data = "nonformal"
    dataset_data = {
        "learner_can_edit_username": True,
        "learner_can_edit_name": True,
        "learner_can_edit_password": True,
        "learner_can_sign_up": True,
        "learner_can_delete_account": True,
        "learner_can_login_with_no_password": False,
    }
    settings = {}
    allow_guest_access = True

    language_id = "en"

    def _default_provision_data(self):
        return {
            "device_name": None,
            "superuser": self.superuser_data,
            "facility": self.facility_data,
            "preset": self.preset_data,
            "settings": self.settings,
            "language_id": self.language_id,
            "allow_guest_access": self.allow_guest_access,
        }

    def _post_deviceprovision(self, data):
        return self.client.post(
            reverse("kolibri:core:deviceprovision"), data, format="json"
        )

    def test_personal_setup_defaults(self):
        data = self._default_provision_data()
        data["preset"] = "informal"
        # Client should pass an empty Dict for settings
        data["settings"] = {}
        self._post_deviceprovision(data)
        settings = FacilityDataset.objects.get()
        self.assertEqual(settings.learner_can_edit_username, True)
        self.assertEqual(settings.learner_can_edit_name, True)
        self.assertEqual(settings.learner_can_edit_password, True)
        self.assertEqual(settings.learner_can_sign_up, True)
        self.assertEqual(settings.learner_can_delete_account, True)
        self.assertEqual(settings.learner_can_login_with_no_password, False)
        self.assertEqual(settings.show_download_button_in_learn, True)

        device_settings = DeviceSettings.objects.get()
        self.assertEqual(device_settings.allow_guest_access, True)

    def test_cannot_post_if_provisioned(self):
        provision_device()
        data = self._default_provision_data()
        response = self._post_deviceprovision(data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_created(self):
        data = self._default_provision_data()
        self._post_deviceprovision(data)
        self.assertEqual(
            FacilityUser.objects.get().username, self.superuser_data["username"]
        )

    def test_superuser_password_set_correctly(self):
        data = self._default_provision_data()
        self._post_deviceprovision(data)
        self.assertTrue(
            FacilityUser.objects.get().check_password(self.superuser_data["password"])
        )

    def test_superuser_device_permissions_created(self):
        data = self._default_provision_data()
        self._post_deviceprovision(data)
        self.assertEqual(
            DevicePermissions.objects.get(),
            FacilityUser.objects.get().devicepermissions,
        )

    def test_facility_created(self):
        data = self._default_provision_data()
        self._post_deviceprovision(data)
        self.assertEqual(Facility.objects.get().name, self.facility_data["name"])

    def test_admin_role_created(self):
        data = self._default_provision_data()
        self._post_deviceprovision(data)
        self.assertEqual(Role.objects.get().kind, ADMIN)

    def test_facility_role_created(self):
        data = self._default_provision_data()
        self._post_deviceprovision(data)
        self.assertEqual(Role.objects.get().collection.name, self.facility_data["name"])

    def test_dataset_set_created(self):
        data = self._default_provision_data()
        self._post_deviceprovision(data)
        self.assertEqual(
            FacilityDataset.objects.get().learner_can_edit_username,
            self.dataset_data["learner_can_edit_username"],
        )
        self.assertEqual(
            FacilityDataset.objects.get().learner_can_edit_name,
            self.dataset_data["learner_can_edit_name"],
        )
        self.assertEqual(
            FacilityDataset.objects.get().learner_can_edit_password,
            self.dataset_data["learner_can_edit_password"],
        )
        self.assertEqual(
            FacilityDataset.objects.get().learner_can_sign_up,
            self.dataset_data["learner_can_sign_up"],
        )
        self.assertEqual(
            FacilityDataset.objects.get().learner_can_delete_account,
            self.dataset_data["learner_can_delete_account"],
        )
        self.assertEqual(
            FacilityDataset.objects.get().learner_can_login_with_no_password,
            self.dataset_data["learner_can_login_with_no_password"],
        )

    def test_device_settings_created(self):
        data = self._default_provision_data()
        self.assertEqual(DeviceSettings.objects.count(), 0)
        self._post_deviceprovision(data)
        self.assertEqual(DeviceSettings.objects.count(), 1)

    def test_device_settings_values(self):
        data = self._default_provision_data()
        data["allow_guest_access"] = False
        self._post_deviceprovision(data)
        device_settings = DeviceSettings.objects.get()
        self.assertEqual(device_settings.default_facility, Facility.objects.get())
        self.assertFalse(device_settings.allow_guest_access)
        self.assertFalse(device_settings.allow_peer_unlisted_channel_import)
        self.assertTrue(device_settings.allow_learner_unassigned_resource_access)

    def test_create_superuser_error(self):
        data = self._default_provision_data()
        data.update({"superuser": {}})
        response = self._post_deviceprovision(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_osuser_superuser_error_no_app(self):
        with plugin_disabled("kolibri.plugins.app"):
            data = self._default_provision_data()
            del data["superuser"]
            response = self._post_deviceprovision(data)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_osuser_superuser_created(self):
        with plugin_enabled("kolibri.plugins.app"), register_capabilities(
            **{GET_OS_USER: lambda x: ("test_user", True)}
        ):
            initialize_url = interface.get_initialize_url(auth_token="test")
            self.client.get(initialize_url)
            data = self._default_provision_data()
            del data["superuser"]
            data.update({"auth_token": "test"})
            self._post_deviceprovision(data)
            self.client.get(initialize_url)
            self.assertEqual(
                DevicePermissions.objects.get(),
                FacilityUser.objects.get().devicepermissions,
            )
            self.assertTrue(FacilityUser.objects.get().os_user)

    def test_imported_facility_no_update(self):
        facility = Facility.objects.create(name="This is a test")
        settings = FacilityDataset.objects.get()
        settings.learner_can_edit_username = True
        settings.save()
        data = self._default_provision_data()
        data["facility_id"] = facility.id
        del data["facility"]
        # Client should pass an empty Dict for settings
        data["settings"] = {
            "learner_can_edit_username": False,
            "on_my_own_setup": True,
        }
        settings.refresh_from_db()
        facility.refresh_from_db()
        self._post_deviceprovision(data)
        self.assertEqual(settings.learner_can_edit_username, True)
        self.assertEqual(facility.on_my_own_setup, False)

    def test_imported_facility_with_fake_facility_id(self):
        data = self._default_provision_data()
        # Fake facility_id
        data["facility_id"] = "12345678123456781234567812345678"
        del data["facility"]
        response = self._post_deviceprovision(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_imported_facility_with_no_facility_data(self):
        data = self._default_provision_data()
        # Try to create facility with no data
        data["facility_id"] = None
        del data["facility"]
        response = self._post_deviceprovision(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class DeviceSettingsTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.settings = {
            "language_id": "en",
            "allow_guest_access": False,
            "allow_peer_unlisted_channel_import": True,
            "allow_learner_unassigned_resource_access": False,
        }

        cls.facility = FacilityFactory.create()
        provision_device(language_id="es", default_facility=cls.facility)
        cls.superuser = create_superuser(cls.facility)
        cls.user = FacilityUserFactory.create(facility=cls.facility)

    def setUp(self):
        super(DeviceSettingsTestCase, self).setUp()
        clear_process_cache()
        self.client.login(
            username=self.superuser.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            reverse("kolibri:core:devicesettings"), self.settings, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_post(self):
        response = self.client.post(
            reverse("kolibri:core:devicesettings"), self.settings, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_cannot_put(self):
        response = self.client.put(
            reverse("kolibri:core:devicesettings"), self.settings, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_patch(self):
        device_settings = DeviceSettings.objects.get()
        self.assertEqual("es", device_settings.language_id)
        self.assertTrue(device_settings.allow_guest_access)
        self.assertFalse(device_settings.allow_peer_unlisted_channel_import)
        self.assertTrue(device_settings.allow_learner_unassigned_resource_access)

        self.client.patch(
            reverse("kolibri:core:devicesettings"), self.settings, format="json"
        )
        device_settings.refresh_from_db()

        self.assertEqual("en", device_settings.language_id)
        self.assertFalse(device_settings.allow_guest_access)
        self.assertTrue(device_settings.allow_peer_unlisted_channel_import)
        self.assertFalse(device_settings.allow_learner_unassigned_resource_access)


class DevicePermissionsTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        clear_process_cache()
        provision_device()
        cls.facility = FacilityFactory.create()
        cls.superuser = create_superuser(cls.facility)
        cls.user = FacilityUserFactory.create(facility=cls.facility)

    def setUp(self):
        self.client.login(
            username=self.superuser.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )

    def test_superuser_delete_own_permissions(self):
        response = self.client.delete(
            reverse(
                "kolibri:core:devicepermissions-detail",
                kwargs={"pk": self.superuser.devicepermissions.pk},
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_update_own_permissions(self):
        response = self.client.patch(
            reverse(
                "kolibri:core:devicepermissions-detail",
                kwargs={"pk": self.superuser.devicepermissions.pk},
            ),
            {"is_superuser": False},
            format="json",
        )
        self.assertEqual(response.status_code, 403)


@override_option("Deployment", "MINIMUM_DISK_SPACE", 0)
class FreeSpaceTestCase(APITestCase):
    def setUp(self):
        clear_process_cache()
        provision_device()
        self.facility = FacilityFactory.create()
        self.superuser = create_superuser(self.facility)
        self.user = FacilityUserFactory.create(facility=self.facility)
        self.client.login(
            username=self.superuser.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )

    def test_posix_freespace(self):
        if not sys.platform.startswith("win"):
            with mock.patch("kolibri.utils.system.os.statvfs") as os_statvfs_mock:
                statvfs_result = namedtuple("statvfs_result", ["f_frsize", "f_bavail"])
                os_statvfs_mock.return_value = statvfs_result(f_frsize=1, f_bavail=2)

                response = self.client.get(
                    reverse("kolibri:core:freespace"), {"path": "test"}
                )

                os_statvfs_mock.assert_called_with(os.path.realpath("test"))
                self.assertEqual(response.data, {"freespace": 2})

    def test_win_freespace_fail(self):
        if sys.platform.startswith("win"):
            ctypes_mock = mock.MagicMock()
            with mock.patch.dict("sys.modules", ctypes=ctypes_mock):
                ctypes_mock.windll.kernel32.GetDiskFreeSpaceExW.return_value = 0
                ctypes_mock.winError.side_effect = OSError
                try:
                    self.client.get(reverse("kolibri:core:freespace"), {"path": "test"})
                except OSError:
                    # check if ctypes.winError() has been called
                    ctypes_mock.winError.assert_called_with()


class DeviceInfoTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        provision_device()
        DatabaseIDModel.objects.create()
        cls.facility = FacilityFactory.create()
        cls.superuser = create_superuser(cls.facility)

    def setUp(self):
        clear_process_cache()
        self.client.login(
            username=self.superuser.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )

    def test_has_version(self):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(response.data["version"], kolibri.__version__)

    def test_urls(self):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertNotEqual(len(response.data["urls"]), 0)
        for url in response.data["urls"]:
            # Make sure each url is a valid link
            self.assertTrue(url.startswith("http://"))

    @patch(
        "kolibri.core.device.api.get_urls",
        return_value=(1, ["http://127.0.0.1:8000", "http://kolibri.com"]),
    )
    def test_no_localhost_urls_when_others_available(self, get_urls_mock):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(len(response.data["urls"]), 1)
        self.assertEqual(response.data["urls"][0], "http://kolibri.com")

    @patch(
        "kolibri.core.device.api.get_urls", return_value=(1, ["http://127.0.0.1:8000"])
    )
    def test_localhost_urls_when_no_others_available(self, get_urls_mock):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(len(response.data["urls"]), 1)
        self.assertEqual(response.data["urls"][0], "http://127.0.0.1:8000")

    def test_database_path(self):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        db_engine = settings.DATABASES["default"]["ENGINE"]
        db_path = response.data["database_path"]
        if db_engine.endswith("sqlite3"):
            self.assertEqual(db_path, settings.DATABASES["default"]["NAME"])
        elif db_engine.endswith("postgresql"):
            self.assertEqual(db_path, "postgresql")
        else:
            self.assertEqual(db_path, "unknown")

    def test_os(self):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(response.data["os"], platform.platform())

    def test_device_id(self):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(
            response.data["device_id"],
            InstanceIDModel.get_or_create_current_instance()[0].id,
        )

    def test_time_zone(self):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertTrue(response.data["server_timezone"], settings.TIME_ZONE)

    def test_free_space(self):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(type(response.data["content_storage_free_space"]), int)

    def test_superuser_permissions(self):
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(response.status_code, 200)

    def test_user_permissions(self):
        self.user = FacilityUserFactory.create(facility=self.facility)
        self.client.logout()
        self.client.login(
            username=self.user.username, password=DUMMY_PASSWORD, facility=self.facility
        )
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(response.status_code, 403)

    def test_user_with_permissions(self):
        self.user = FacilityUserFactory.create(facility=self.facility)
        DevicePermissions.objects.create(user=self.user, can_manage_content=True)
        self.client.logout()
        self.client.login(
            username=self.user.username, password=DUMMY_PASSWORD, facility=self.facility
        )
        response = self.client.get(reverse("kolibri:core:deviceinfo"), format="json")
        self.assertEqual(response.status_code, 200)


class DeviceNameTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.device_name = {"name": "test device"}
        cls.facility = FacilityFactory.create()
        provision_device(language_id="es", default_facility=cls.facility)
        cls.superuser = create_superuser(cls.facility)
        cls.user = FacilityUserFactory.create(facility=cls.facility)

    def setUp(self):
        clear_process_cache()
        super(DeviceNameTestCase, self).setUp()
        self.client.login(
            username=self.superuser.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            reverse("kolibri:core:devicename"), self.device_name, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_existing_device_name(self):
        response = self.client.get(reverse("kolibri:core:devicename"))
        self.assertEqual(
            response.data["name"],
            InstanceIDModel.get_or_create_current_instance()[0].hostname,
        )

    def test_patch(self):
        device_settings = DeviceSettings.objects.get()
        self.assertEqual(
            device_settings.name,
            InstanceIDModel.get_or_create_current_instance()[0].hostname,
        )

        response = self.client.patch(
            reverse("kolibri:core:devicename"), self.device_name, format="json"
        )
        self.assertEqual(response.data, self.device_name)
        device_settings.refresh_from_db()

        self.assertEqual(device_settings.name, self.device_name["name"])
        self.assertNotEqual(
            device_settings.name,
            InstanceIDModel.get_or_create_current_instance()[0].hostname,
        )

    def test_device_name_max_length(self):
        with self.assertRaises(ValidationError):
            exceeds_max_length_name = {"name": "a" * 60}
            self.client.patch(
                reverse("kolibri:core:devicename"),
                exceeds_max_length_name,
                format="json",
            )


class UserSyncStatusTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        provision_device()
        cls.facility = FacilityFactory.create()
        cls.superuser = create_superuser(cls.facility)
        cls.user1 = FacilityUserFactory.create(facility=cls.facility)
        cls.user2 = FacilityUserFactory.create(facility=cls.facility)
        cls.classroom = ClassroomFactory.create(parent=cls.facility)
        cls.classroom.add_member(cls.user1)
        cls.classroom.add_coach(cls.superuser)
        syncdata = {
            "id": uuid.uuid4().hex,
            "start_timestamp": timezone.now(),
            "last_activity_timestamp": timezone.now(),
            "active": False,
            "is_server": False,
            "client_instance_id": None,
            "server_instance_id": None,
            "extra_fields": {},
        }
        cls.syncsession1 = SyncSession.objects.create(**syncdata)
        data1 = {
            "user_id": cls.user1.id,
            "sync_session": cls.syncsession1,
            "queued": True,
        }
        cls.syncstatus1 = UserSyncStatus.objects.create(**data1)

        syncdata2 = {
            "id": uuid.uuid4().hex,
            "start_timestamp": timezone.now(),
            "last_activity_timestamp": timezone.now(),
            "active": False,
            "is_server": False,
            "client_instance_id": None,
            "server_instance_id": None,
            "extra_fields": {},
        }
        cls.syncsession2 = SyncSession.objects.create(**syncdata2)
        data2 = {
            "user_id": cls.user2.id,
            "sync_session": cls.syncsession2,
            "queued": False,
        }
        cls.syncstatus2 = UserSyncStatus.objects.create(**data2)

    def _create_transfer_session(self, **data):
        defaults = dict(
            id=uuid.uuid4(),
            filter="no-filter",
            push=True,
            active=True,
            sync_session=self.syncsession1,
            last_activity_timestamp=timezone.now(),
            transfer_stage_status=transfer_statuses.COMPLETED,
        )
        defaults.update(data)
        TransferSession.objects.create(**defaults)

    def _create_device_status(self, *status):
        instance_id = uuid.uuid4()
        return LearnerDeviceStatus.objects.create(
            instance_id=instance_id,
            user=self.user1,
            **dict(zip(("status", "status_sentiment"), status))
        )

    def setUp(self):
        clear_process_cache()
        self.client.login(
            username=self.superuser.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )

    def test_usersyncstatus_list(self):
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        expected_count = UserSyncStatus.objects.count()
        self.assertEqual(len(response.data), expected_count)

    def test_user_sync_status_class_single_user_for_filter(self):
        response = self.client.get(
            reverse("kolibri:core:usersyncstatus-list"),
            data={"user": self.user1.id},
        )
        expected_count = UserSyncStatus.objects.filter(user_id=self.user1.id).count()
        self.assertEqual(len(response.data), expected_count)

    def test_user_sync_status_class_list_for_filter(self):
        response = self.client.get(
            reverse("kolibri:core:usersyncstatus-list"),
            data={"member_of": self.classroom.id},
        )
        self.assertEqual(len(response.data), 1)

    def test_usersyncstatus_list_learner_permissions(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)

    def test_usersyncstatus_list_facility_admin_permissions(self):
        fadmin = FacilityUserFactory.create(facility=self.facility)
        self.facility.add_admin(fadmin)
        self.client.login(
            username=fadmin.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        expected_count = UserSyncStatus.objects.count()
        self.assertEqual(len(response.data), expected_count)

    def test_usersyncstatus_list_facility_coach_permissions(self):
        fcoach = FacilityUserFactory.create(facility=self.facility)
        self.facility.add_coach(fcoach)
        self.client.login(
            username=fcoach.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        expected_count = UserSyncStatus.objects.count()
        self.assertEqual(len(response.data), expected_count)

    def test_usersyncstatus_list_class_coach_permissions(self):
        ccoach = FacilityUserFactory.create(facility=self.facility)
        self.classroom.add_coach(ccoach)
        self.client.login(
            username=ccoach.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)

    def test_usersyncstatus_list_learner_error_state(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            transfer_stage_status=transfer_statuses.ERRORED,
        )

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.UNABLE_TO_SYNC)

    def test_usersyncstatus_list_learner_syncing_state(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            transfer_stage_status=transfer_statuses.STARTED,
        )

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.SYNCING)

    def test_usersyncstatus_list_learner_syncing_state_old_error(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            last_activity_timestamp=timezone.now() - timedelta(seconds=100),
            transfer_stage_status=transfer_statuses.ERRORED,
        )
        self._create_transfer_session(
            transfer_stage_status=transfer_statuses.STARTED,
        )

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.SYNCING)

    def test_usersyncstatus_list_learner_recent_success(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self.syncstatus1.queued = False
        self.syncstatus1.save()
        self._create_transfer_session(
            active=False,
        )

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.RECENTLY_SYNCED)

    def test_usersyncstatus_list_learner_queued(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        last_sync = timezone.now() - timedelta(seconds=DELAYED_SYNC * 2)
        self.syncsession1.last_activity_timestamp = last_sync
        self.syncsession1.save()
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.QUEUED)

    def test_usersyncstatus_list_learner_queued_recent_success(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )

        self._create_transfer_session(
            active=False,
        )
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.RECENTLY_SYNCED)

    def test_usersyncstatus_list_learner_queued_not_recent_success(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )

        last_sync = timezone.now() - timedelta(seconds=DELAYED_SYNC * 2)
        self.syncsession1.last_activity_timestamp = last_sync
        self.syncsession1.save()
        self._create_transfer_session(
            active=False,
            last_activity_timestamp=last_sync,
        )

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.QUEUED)

    def test_usersyncstatus_list_learner_not_recent_success(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self.syncstatus1.queued = False
        self.syncstatus1.save()
        last_sync = timezone.now() - timedelta(seconds=DELAYED_SYNC * 2)
        self.syncsession1.last_activity_timestamp = last_sync
        self.syncsession1.save()
        self._create_transfer_session(
            active=False,
            last_activity_timestamp=last_sync,
        )

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(
            response.data[0]["status"], user_sync_statuses.NOT_RECENTLY_SYNCED
        )

    def test_usersyncstatus_list_learner_no_sync_session(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self.syncstatus1.queued = False
        previous_sync_session = self.syncstatus1.sync_session
        self.syncstatus1.sync_session = None
        self.syncstatus1.save()

        try:
            response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
            self.assertEqual(len(response.data), 1)
            self.assertEqual(response.data[0]["user"], self.user1.id)
            self.assertEqual(
                response.data[0]["status"], user_sync_statuses.NOT_RECENTLY_SYNCED
            )
        finally:
            # Not doing this leads to weird unexpected test contagion.
            self.syncstatus1.sync_session = previous_sync_session
            self.syncstatus1.save()

    def test_usersyncstatus_list__insufficient_storage(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            active=False,
        )
        device_status = self._create_device_status(*DeviceStatus.InsufficientStorage)
        self.syncsession1.client_instance_id = device_status.instance_id
        self.syncsession1.save()

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(
            response.data[0]["status"], user_sync_statuses.INSUFFICIENT_STORAGE
        )

    def test_usersyncstatus_list__unknown_negative_device_status(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            active=False,
        )
        device_status = self._create_device_status("oopsie", StatusSentiment.Negative)
        self.syncsession1.client_instance_id = device_status.instance_id
        self.syncsession1.save()

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.UNABLE_TO_SYNC)

    def test_usersyncstatus_list__unknown_non_negative_device_status(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            active=False,
        )
        device_status = self._create_device_status("oopsie", StatusSentiment.Neutral)
        self.syncsession1.client_instance_id = device_status.instance_id
        self.syncsession1.save()

        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.RECENTLY_SYNCED)

    def test_downloads_queryset(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            active=False,
        )
        content_request = ContentDownloadRequest.build_for_user(self.user1)
        content_request.contentnode_id = uuid.uuid4().hex
        device_status = self._create_device_status("oopsie", StatusSentiment.Neutral)
        self.syncsession1.client_instance_id = device_status.instance_id
        self.syncsession1.save()
        content_request.save()
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["user"], self.user1.id)
        self.assertEqual(response.data[0]["status"], user_sync_statuses.RECENTLY_SYNCED)
        self.assertTrue(response.data[0]["has_downloads"])
        self.assertIsNone(response.data[0]["last_download_removed"])

    def test_downloads_queryset__content_request_removed(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            active=False,
        )
        content_request = ContentDownloadRequest.build_for_user(self.user1)
        content_request.contentnode_id = uuid.uuid4().hex
        content_request.save()
        content_removal_request = ContentRemovalRequest.build_for_user(self.user1)
        content_removal_request.contentnode_id = content_request.contentnode_id
        content_removal_request.save()
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertFalse(response.data[0]["has_downloads"])

    def test_downloads_queryset__sync_downloads_in_progress(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            active=False,
        )
        content_request = ContentDownloadRequest.build_for_user(self.user1)
        content_request.contentnode_id = uuid.uuid4().hex
        content_request.reason = ContentRequestReason.SyncInitiated
        content_request.save()
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertTrue(response.data[0]["sync_downloads_in_progress"])

    def test_downloads_queryset__sync_downloads_in_progress_removed(self):
        self.client.login(
            username=self.user1.username,
            password=DUMMY_PASSWORD,
            facility=self.facility,
        )
        self._create_transfer_session(
            active=False,
        )
        content_request = ContentDownloadRequest.build_for_user(self.user1)
        content_request.contentnode_id = uuid.uuid4().hex
        content_request.reason = ContentRequestReason.SyncInitiated
        content_request.save()
        content_removal_request = ContentRemovalRequest.build_for_user(self.user1)
        content_removal_request.contentnode_id = content_request.contentnode_id
        content_removal_request.reason = ContentRequestReason.SyncInitiated
        content_removal_request.save()
        response = self.client.get(reverse("kolibri:core:usersyncstatus-list"))
        self.assertFalse(response.data[0]["sync_downloads_in_progress"])
