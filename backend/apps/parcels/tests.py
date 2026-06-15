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
        LockerCell.objects.create(code="A001", zone="A区", size=LockerCell.Size.SMALL)
        LockerCell.objects.create(code="A002", zone="A区", size=LockerCell.Size.SMALL)
        LockerCell.objects.create(code="A003", zone="A区", size=LockerCell.Size.MEDIUM)
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

    def test_duplicate_tracking_no_cell_not_occupied(self):
        initial_empty_count = LockerCell.objects.filter(
            status=LockerCell.Status.EMPTY
        ).count()
        inbound_parcel(self.data.copy())
        self.assertEqual(
            LockerCell.objects.filter(status=LockerCell.Status.EMPTY).count(),
            initial_empty_count - 1,
        )
        try:
            inbound_parcel(self.data.copy())
        except ValidationError:
            pass
        self.assertEqual(
            LockerCell.objects.filter(status=LockerCell.Status.EMPTY).count(),
            initial_empty_count - 1,
        )


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

    def test_open_by_pickup_code_cell_becomes_open(self):
        open_by_pickup_code("654321")
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OPEN)
        self.assertIsNotNone(self.cell.last_opened_at)

    def test_open_by_pickup_code_status_linkage(self):
        parcel = open_by_pickup_code("654321")
        self.cell.refresh_from_db()
        self.assertEqual(parcel.status, Parcel.Status.PICKED_UP)
        self.assertEqual(self.cell.status, LockerCell.Status.OPEN)

    def test_open_by_pickup_code_invalid_code(self):
        parcel = open_by_pickup_code("000000")
        self.assertIsNone(parcel)
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

    def test_open_by_pickup_code_already_picked_up(self):
        self.parcel.status = Parcel.Status.PICKED_UP
        self.parcel.save()
        parcel = open_by_pickup_code("654321")
        self.assertIsNone(parcel)
        self.cell.refresh_from_db()
        self.assertEqual(self.cell.status, LockerCell.Status.OCCUPIED)

    def test_open_by_pickup_code_return_pending(self):
        self.parcel.status = Parcel.Status.RETURN_PENDING
        self.parcel.save()
        parcel = open_by_pickup_code("654321")
        self.assertIsNone(parcel)
