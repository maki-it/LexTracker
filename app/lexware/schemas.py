"""The parts of Lexware Office API responses that LexTracker uses.

See https://developers.lexware.io/docs/#contacts-endpoint
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class CustomerRole(_Model):
    number: int | None = None


class Roles(_Model):
    customer: CustomerRole | None = None


class ContactPerson(_Model):
    first_name: str = Field("", alias="firstName")
    last_name: str = Field("", alias="lastName")
    email_address: str = Field("", alias="emailAddress")
    phone_number: str = Field("", alias="phoneNumber")
    primary: bool = False


class Company(_Model):
    name: str = ""
    contact_persons: list[ContactPerson] = Field(default_factory=list, alias="contactPersons")


class Person(_Model):
    first_name: str = Field("", alias="firstName")
    last_name: str = Field("", alias="lastName")


class EmailAddresses(_Model):
    business: list[str] = Field(default_factory=list)
    office: list[str] = Field(default_factory=list)
    private: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)


class PhoneNumbers(_Model):
    business: list[str] = Field(default_factory=list)
    office: list[str] = Field(default_factory=list)
    mobile: list[str] = Field(default_factory=list)
    private: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)


class Contact(_Model):
    id: UUID
    version: int
    archived: bool = False
    roles: Roles = Field(default_factory=Roles)
    company: Company | None = None
    person: Person | None = None
    email_addresses: EmailAddresses = Field(default_factory=EmailAddresses, alias="emailAddresses")
    phone_numbers: PhoneNumbers = Field(default_factory=PhoneNumbers, alias="phoneNumbers")
    note: str = ""

    @property
    def name(self) -> str:
        if self.company and self.company.name:
            return self.company.name
        if self.person:
            return f"{self.person.first_name} {self.person.last_name}".strip()
        return ""

    @property
    def customer_number(self) -> str:
        number = self.roles.customer.number if self.roles.customer else None
        return str(number) if number is not None else ""

    def _primary_contact_person(self) -> ContactPerson | None:
        persons = self.company.contact_persons if self.company else []
        return next((p for p in persons if p.primary), persons[0] if persons else None)

    @property
    def email(self) -> str:
        e = self.email_addresses
        for address in (*e.business, *e.office, *e.other, *e.private):
            return address
        person = self._primary_contact_person()
        return person.email_address if person else ""

    @property
    def phone(self) -> str:
        p = self.phone_numbers
        for number in (*p.business, *p.office, *p.mobile, *p.other, *p.private):
            return number
        person = self._primary_contact_person()
        return person.phone_number if person else ""


class Profile(_Model):
    """The organization behind the API key. See https://developers.lexware.io/docs/#profile-endpoint"""

    company_name: str = Field("", alias="companyName")
    # How the organization enters prices by default: "net", "gross" or "vatfree".
    tax_type: str = Field("net", alias="taxType")
    # Small business under § 19 UStG: invoices carry no VAT.
    small_business: bool = Field(False, alias="smallBusiness")


class ContactPage(_Model):
    content: list[Contact]
    last: bool
    number: int
    total_pages: int = Field(alias="totalPages")


class Voucher(_Model):
    """An entry of the voucher list. See https://developers.lexware.io/docs/#voucherlist-endpoint"""

    id: UUID
    voucher_status: str = Field(alias="voucherStatus")
    voucher_number: str | None = Field(None, alias="voucherNumber")
    voucher_date: datetime | None = Field(None, alias="voucherDate")
    due_date: datetime | None = Field(None, alias="dueDate")
    contact_id: UUID | None = Field(None, alias="contactId")
    open_amount: float | None = Field(None, alias="openAmount")


class VoucherPage(_Model):
    content: list[Voucher]
    last: bool
    number: int
    total_pages: int = Field(alias="totalPages")
