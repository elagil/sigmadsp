"""This module describes the header of a packet that is exchanged with SigmaStudio.

Headers contain individual fields that follow each other in a certain sequence."""

from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, List, Literal

from sigmadsp.helper.conversion import bytes_to_int, int_to_bytes


class OperationKey(Enum):
    READ_REQUEST_KEY = 0x0A
    READ_RESPONSE_KEY = 0x0B
    WRITE_KEY = 0x09


VALID_FIELD_NAMES = Literal[
    "operation", "safeload", "channel", "total_length", "chip_address", "data_length", "address", "success", "reserved"
]


@dataclass
class Field:
    """A class that represents a single field in the header."""

    # The name of the field.
    name: VALID_FIELD_NAMES

    # The offset of the field in bytes from the start of the header.
    offset: int

    # The size of the field in bytes.
    size: int

    # The stored value.
    value: int = 0

    def __post_init__(self):
        """Perform sanity checks on the field properties."""
        if self.size < 0:
            raise ValueError("Field size must be a positive integer.")

        if self.offset < 0:
            raise ValueError("Field offset must be a positive integer.")

        # The last byte index that is occupied by this field.
        self.end = self.offset + self.size - 1

    def __hash__(self) -> int:
        """Hash functionality."""
        return hash((self.name, self.offset, self.size))


class PacketHeader(ABC):
    """An iterable collection of Field objects that forms the packet header."""

    def __init__(self, fields: List[Field]):
        """Initialize the header fields. Add more fields to it by means of `add()`.

        Instantiate via:
        PacketHeader(
            [
                Field("field_name", 0, 4),
                Field("next_field_name", 4, 1),
                # ...
            ]
        )

        Args:
            fields (List[Field]): The list of fields to add initially.
        """
        self._fields: OrderedDict[str, Field] = OrderedDict()  # pylint: disable=E1136

        for field in fields:
            self.add_field(field)

    @property
    def size(self) -> int:
        """The total size of the header in bytes."""
        return sum([field.size for field in self])

    @property
    def is_continuous(self) -> bool:
        """Whether or not there are spaces in the header that are not defined."""
        fields_entries = self.as_list()

        for field, next_field in zip(fields_entries, fields_entries[1:]):
            if (field.end + 1) != next_field.offset:
                return False

        return True

    def _check_for_overlaps(self):
        """Check for overlapping fields.

        Raises:
            MemoryError: If overlapping fields are found.
        """
        fields_entries = self.as_list()

        # Check for overlapping fields, which are sorted by their offset.
        for field, next_field in zip(fields_entries, fields_entries[1:]):
            if not field.end <= next_field.offset:
                raise MemoryError("Fields {field.name} and {next_field.name} overlap.")

    def _sort_fields_by_offset(self):
        """Sorts the fields in this header by their offset."""
        self._fields = OrderedDict(sorted(self._fields.items(), key=lambda item: item[1].offset))

    def add(self, name: VALID_FIELD_NAMES, offset: int, size: int, value: int = 0):
        field = Field(name, offset, size, value)
        self.add_field(field)

    def add_field(self, field: Field):
        """Add a new field. Duplicates are ignored.

        Args:
            field (Field): The field to add.
        """
        if field not in self:
            self._fields[field.name] = field

            self._sort_fields_by_offset()
            self._check_for_overlaps()

    def as_bytes(self) -> bytes:
        """Get the full header as a bytes object."""
        buffer = bytearray()

        for field in self:
            int_to_bytes(field.value, buffer, field.offset, field.size)

        return bytes(buffer)

    def as_list(self) -> List[Field]:
        """The fields as a list.

        Returns:
            List[Field]: The list of fields.
        """
        return list(self._fields.values())

    def parse(self, data: bytes):
        """Parse a header and populate field values.

        Args:
            data (bytes): The data to parse.
        """
        if len(data) != self.size:
            raise ValueError(f"Input data needs to be exactly {self.size} bytes long!")

        for field in self:
            field.value = bytes_to_int(data, field.offset, field.size)

    @property
    def is_write_request(self) -> bool:
        """Whether this is a write request."""
        return self._fields["operation"].value == OperationKey.WRITE_KEY

    @property
    def is_read_request(self) -> bool:
        """Whether this is a read request."""
        return self._fields["operation"].value == OperationKey.READ_REQUEST_KEY

    @property
    def is_read_response(self) -> bool:
        """Whether this is a read response."""
        return self._fields["operation"].value == OperationKey.READ_RESPONSE_KEY

    @property
    def is_safeload(self) -> bool:
        """Whether this is a software-safeload write request."""
        return self.is_write_request and self._fields["safeload"].value == 1

    @property
    def carries_payload(self) -> bool:
        """Whether the corresponding packet carries a payload."""
        return self.is_write_request or self.is_read_response

    @property
    def names(self) -> List[str]:
        return [field.name for field in self]

    def __iter__(self) -> Iterator[Field]:
        """The iterator for fields."""
        for item in self._fields.values():
            yield item

    def __setitem__(self, name: VALID_FIELD_NAMES, value: int):
        """Set a field value.

        Args:
            name (VALID_FIELD_NAMES): Field name.
            value (int): Field value.
        """
        if name not in self.names:
            raise ValueError(f"Invalid field name {name}; valid names are {', '.join(self.names)}")

        self._fields[name].value = value

    def __getitem__(self, name: VALID_FIELD_NAMES) -> Field:
        """Get a field by its name.

        Args:
            name (VALID_FIELD_NAMES): The name of the field.

        Returns:
            Union[Field, None]: The field, or None, if no field was found.

        Raises:
            IndexError: If the field does not exist.
        """
        return self._fields[name]

    def __contains__(self, name: VALID_FIELD_NAMES) -> bool:
        """Magic methods for using `in`.

        Args:
            name (VALID_FIELD_NAMES): The name to look for in the fields.

        Returns:
            bool: True, if a field with the given name exists.
        """
        return name in self._fields


class PacketHeaderGenerator(ABC):
    @abstractmethod
    @staticmethod
    def new_write_header() -> PacketHeader:
        """Generate a new header for a write packet."""

    @abstractmethod
    @staticmethod
    def new_read_request_header() -> PacketHeader:
        """Generate a new header for a read request packet."""

    @abstractmethod
    @staticmethod
    def new_read_response_header() -> PacketHeader:
        """Generate a new header for a read response packet."""

    def new_header_from_operation_byte(self, operation_byte: bytes) -> PacketHeader:
        assert len(operation_byte) == 1, "Operation byte must have a length of 1."

        operation_key = OperationKey(bytes_to_int(operation_byte, offset=0, length=1))

        if operation_key == OperationKey.READ_REQUEST_KEY:
            return self.new_read_request_header()

        elif operation_key == OperationKey.READ_RESPONSE_KEY:
            return self.new_read_response_header()

        elif operation_key == OperationKey.WRITE_KEY:
            return self.new_write_header()

        else:
            raise ValueError(f"Unknown operation key {operation_key}.")
