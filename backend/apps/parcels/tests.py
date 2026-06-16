from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.lockers.models import LockerCell
from apps.parcels.models import Parcel
from apps.parcels.services import inbound_parcel, open_by_pickup_code, generate_pickup_code


class InboundParcelTests(TestCase):
    def setUp(self):
        self.cell_small = LockerCell.objects.create(
            code="A001", zone="A区", size=LockerCell.Size.SMALL
        )
        self.cell_medium = LockerCell.objects.create(
            code="B001", zone="A区", size=LockerCell.Size.MEDIUM
        )
        self.cell_large = LockerCell.objects.create(
            code="C001", zone="A区", size=LockerCell.Size.LARGE
        )
        self.valid_data = {
            "tracking_no": "SF1234567890",
            "sender_name": "张三",
            "receiver_name": "李四",
            "receiver_phone": "13800138000",
            "carrier": "顺丰",
        }

    def test_inbound_parcel_success(self):
        parcel = inbound_parcel(self.valid_data.copy())
        self.assertEqual(parcel.tracking_no, "SF1234567890")
        self.assertEqual(parcel.status, Parcel.Status.STORED)
        self.assertIsNotNone(parcel.pickup_code)
        self.assertEqual(len(parcel.pickup_code), 6)
        self.assertIsNotNone(parcel.stored_at)

    def test_inbound_parcel_assigns_empty_cell(self):
        parcel = inbound_parcel(self.valid_data.copy())
        cell = LockerCell.objects.get(id=parcel.locker_cell_id)
        self.assertEqual(cell.status, LockerCell.Status.OCCUPIED)
        self.assertEqual(cell.id, self.cell_small.id)

    def test_inbound_parcel_with_size_filter(self):
        data = self.valid_data.copy()
        data["size"] = LockerCell.Size.LARGE
        parcel = inbound_parcel(data)
        self.assertEqual(parcel.locker_cell.id, self.cell_large.id)

    def test_inbound_parcel_no_available_cell(self):
        LockerCell.objects.all().update(status=LockerCell.Status.OCCUPIED)
        with self.assertRaises(ValidationError) as ctx:
            inbound_parcel(self.valid_data.copy())
        self.assertIn("没有可用柜格", str(ctx.exception))

    def test_inbound_parcel_no_available_cell_of_size(self):
        LockerCell.objects.filter(size=LockerCell.Size.SMALL).update(
            status=LockerCell.Status.OCCUPIED
        )
        data = self.valid_data.copy()
        data["size"] = LockerCell.Size.SMALL
        data["tracking_no"] = "SF9999999999"
        with self.assertRaises(ValidationError) as ctx:
            inbound_parcel(data)
        self.assertIn("没有可用柜格", str(ctx.exception))

    def test_inbound_parcel_status_linkage(self):
        parcel = inbound_parcel(self.valid_data.copy())
        cell = LockerCell.objects.get(id=parcel.locker_cell_id)
        self.assertEqual(parcel.status, Parcel.Status.STORED)
        self.assertEqual(cell.status, LockerCell.Status.OCCUPIED)
        self.assertIsNotNone(cell.updated_at)


class DuplicateTrackingNoTests(TestCase):
    def setUp(self):
        self.cell1 = LockerCell.objects.create(code="A001", zone="A区", size=LockerCell.Size.SMALL)
        self.cell2 = LockerCell.objects.create(code="A002", zone="A区", size=LockerCell.Size.SMALL)
        self.cell3 = LockerCell.objects.create(code="A003", zone="A区", size=LockerCell.Size.MEDIUM)
        self.data = {
            "tracking_no": "SF1234567890",
            "sender_name": "张三",
            "receiver_name": "李四",
            "receiver_phone": "13800138000",
            "carrier": "顺丰",
        }

    def test_duplicate_tracking_no_raises_error(self):
        inbound_parcel(self.data.copy())
        with self.assertRaises(ValidationError) as ctx:
            inbound_parcel(self.data.copy())
        self.assertIn("该运单号已经入库", str(ctx.exception))

    def test_duplicate_tracking_no_existing_parcel_unchanged(self):
        original_parcel = inbound_parcel(self.data.copy())
        original_cell_id = original_parcel.locker_cell_id
        original_pickup_code = original_parcel.pickup_code
        original_status = original_parcel.status
        original_stored_at = original_parcel.stored_at

        try:
            inbound_parcel(self.data.copy())
        except ValidationError:
            pass

        original_parcel.refresh_from_db()
        self.assertEqual(original_parcel.locker_cell_id, original_cell_id)
        self.assertEqual(original_parcel.pickup_code, original_pickup_code)
        self.assertEqual(original_parcel.status, original_status)
        self.assertEqual(original_parcel.stored_at, original_stored_at)

    def test_duplicate_tracking_no_existing_cell_unchanged(self):
        parcel = inbound_parcel(self.data.copy())
        cell = LockerCell.objects.get(id=parcel.locker_cell_id)
        self.assertEqual(cell.status, LockerCell.Status.OCCUPIED)

        try:
            inbound_parcel(self.data.copy())
        except ValidationError:
            pass

        cell.refresh_from_db()
        self.assertEqual(cell.status, LockerCell.Status.OCCUPIED)

    def test_duplicate_tracking_no_other_cells_unchanged(self):
        inbound_parcel(self.data.copy())
        empty_count_before = LockerCell.objects.filter(status=LockerCell.Status.EMPTY).count()

        try:
            inbound_parcel(self.data.copy())
        except ValidationError:
            pass

        empty_count_after = LockerCell.objects.filter(status=LockerCell.Status.EMPTY).count()
        self.assertEqual(empty_count_before, empty_count_after)


class PickupCodeTests(TestCase):
    def setUp(self):
        self.cell = LockerCell.objects.create(
            code="M001", zone="A区", size=LockerCell.Size.MEDIUM
        )

    def test_generate_pickup_code_length(self):
        code = generate_pickup_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_generate_pickup_code_unique(self):
        codes = set()
        for _ in range(10):
            code = generate_pickup_code()
            self.assertNotIn(code, codes)
            codes.add(code)

    def test_generate_pickup_code_skips_used(self):
        Parcel.objects.create(
            tracking_no="SF0000000001",
            sender_name="发件人",
            receiver_name="收件人",
            receiver_phone="13800000001",
            carrier="顺丰",
            locker_cell=self.cell,
            pickup_code="123456",
            status=Parcel.Status.STORED,
        )
        code = generate_pickup_code()
        self.assertNotEqual(code, "123456")


class OpenByPickupCodeTests(TestCase):
    def setUp(self):
        self.cell = LockerCell.objects.create(
            code="M001", zone="A区", size=LockerCell.Size.MEDIUM,
            status=LockerCell.Status.OCCUPIED,
        )
        self.parcel = Parcel.objects.create(
            tracking_no="SF1234567890",
            sender_name="张三",
            receiver_name="李四",
            receiver_phone="13800138000",
            carrier="顺丰",
            locker_cell=self.cell,
            pickup_code="654321",
            status=Parcel.Status.STORED,
        )

    def test_open_by_pickup_code_success(self):
        parcel = open_by_pickup_code("654321")
        self.assertIsNotNone(parcel)
        self.assertEqual(parcel.id, self.parcel.id)
        self.assertEqual(parcel.status, Parcel.Status.PICKED_UP)
        self.assertIsNotNone(parcel.picked_up_at)

    def test_open_by_pickup_code_cell_becomes_empty(self):
        open_by_pickup_code("654321")
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.EMPTY)
        self.assertIsNotNone(self.cell.last_opened_at)

    def test_open_by_pickup_code_status_linkage(self):
        parcel = open_by_pickup_code("654321")
        self.cell.refresh_from_db()
        self.assertEqual(parcel.status, Parcel.Status.PICKED_UP)
        self.assertEqual(self.cell.status, LockerCell.Status.EMPTY)

    def test_open_by_pickup_code_invalid_code(self):
        with self.assertRaises(ValidationError) as ctx:
            open_by_pickup_code("000000")
        self.assertIn("取件码无效", str(ctx.exception))
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

    def test_open_by_pickup_code_already_picked_up(self):
        self.parcel.status = Parcel.Status.PICKED_UP
        self.parcel.save()
        with self.assertRaises(ValidationError) as ctx:
            open_by_pickup_code("654321")
        self.assertIn("该快件不可取件", str(ctx.exception))
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

    def test_open_by_pickup_code_return_pending(self):
        self.parcel.status = Parcel.Status.RETURN_PENDING
        self.parcel.save()
        with self.assertRaises(ValidationError) as ctx:
            open_by_pickup_code("654321")
        self.assertIn("该快件正在退件中", str(ctx.exception))
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

    def test_open_by_pickup_code_returned_parcel(self):
        self.parcel.status = Parcel.Status.RETURNED
        self.parcel.save()
        with self.assertRaises(ValidationError) as ctx:
            open_by_pickup_code("654321")
        self.assertIn("该快件不可取件", str(ctx.exception))
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)


class FullPickupFlowTests(TestCase):
    def setUp(self):
        self.cell = LockerCell.objects.create(
            code="A001", zone="A区", size=LockerCell.Size.MEDIUM,
            status=LockerCell.Status.EMPTY,
        )
        self.inbound_data = {
            "tracking_no": "SF1234567890",
            "sender_name": "张三",
            "receiver_name": "李四",
            "receiver_phone": "13800138000",
            "carrier": "顺丰",
        }

    def test_full_inbound_to_pickup_flow(self):
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.EMPTY)

        parcel = inbound_parcel(self.inbound_data.copy())
        self.assertEqual(parcel.status, Parcel.Status.STORED)
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

        result = open_by_pickup_code(parcel.pickup_code)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, Parcel.Status.PICKED_UP)
        self.assertIsNotNone(result.picked_up_at)

        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.EMPTY)
        self.assertIsNotNone(self.cell.last_opened_at)

    def test_cell_can_be_reused_after_pickup(self):
        parcel1 = inbound_parcel(self.inbound_data.copy())
        self.assertEqual(parcel1.locker_cell.id, self.cell.id)
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

        open_by_pickup_code(parcel1.pickup_code)
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.EMPTY)

        second_data = self.inbound_data.copy()
        second_data["tracking_no"] = "SF9999999999"
        parcel2 = inbound_parcel(second_data)
        self.assertEqual(parcel2.locker_cell.id, self.cell.id)
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)


class ConcurrentInboundTests(TestCase):
    def setUp(self):
        self.cell1 = LockerCell.objects.create(
            code="A001", zone="A区", size=LockerCell.Size.MEDIUM,
            status=LockerCell.Status.EMPTY,
        )
        self.cell2 = LockerCell.objects.create(
            code="A002", zone="A区", size=LockerCell.Size.MEDIUM,
            status=LockerCell.Status.EMPTY,
        )
        self.inbound_data = {
            "tracking_no": "SF1234567890",
            "sender_name": "张三",
            "receiver_name": "李四",
            "receiver_phone": "13800138000",
            "carrier": "顺丰",
        }

    def test_duplicate_inbound_returns_friendly_error(self):
        first_parcel = inbound_parcel(self.inbound_data.copy())
        self.assertIsNotNone(first_parcel)

        with self.assertRaises(ValidationError) as ctx:
            inbound_parcel(self.inbound_data.copy())
        self.assertIn("该运单号已经入库", str(ctx.exception))

    def test_duplicate_inbound_first_parcel_unchanged(self):
        first_parcel = inbound_parcel(self.inbound_data.copy())
        original_cell_id = first_parcel.locker_cell_id
        original_pickup_code = first_parcel.pickup_code

        try:
            inbound_parcel(self.inbound_data.copy())
        except ValidationError:
            pass

        first_parcel.refresh_from_db()
        self.assertEqual(first_parcel.locker_cell_id, original_cell_id)
        self.assertEqual(first_parcel.pickup_code, original_pickup_code)
        self.assertEqual(first_parcel.status, Parcel.Status.STORED)

    def test_duplicate_inbound_second_cell_not_wasted(self):
        empty_count_before = LockerCell.objects.filter(
            status=LockerCell.Status.EMPTY
        ).count()

        inbound_parcel(self.inbound_data.copy())
        self.assertEqual(
            LockerCell.objects.filter(status=LockerCell.Status.EMPTY).count(),
            empty_count_before - 1,
        )

        try:
            inbound_parcel(self.inbound_data.copy())
        except ValidationError:
            pass

        self.assertEqual(
            LockerCell.objects.filter(status=LockerCell.Status.EMPTY).count(),
            empty_count_before - 1,
        )

    def test_inbound_integrity_error_handled_gracefully(self):
        from unittest.mock import patch
        from django.db import IntegrityError

        with patch.object(Parcel.objects, "filter") as mock_filter:
            mock_filter.return_value.exists.return_value = False
            mock_filter.return_value.first.return_value = None

            original_create = Parcel.objects.create

            def mock_create(**kwargs):
                if kwargs["tracking_no"] == self.inbound_data["tracking_no"]:
                    raise IntegrityError("UNIQUE constraint failed")
                return original_create(**kwargs)

            Parcel.objects.create = mock_create
            try:
                with self.assertRaises(ValidationError) as ctx:
                    inbound_parcel(self.inbound_data.copy())
                self.assertIn("该运单号已经入库", str(ctx.exception))
            finally:
                Parcel.objects.create = original_create
