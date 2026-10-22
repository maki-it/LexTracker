from django import forms


class StyledFormMixin:
    """Give every widget the app's input styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "size-4 accent-primary")
            else:
                widget.attrs.setdefault("class", "input")
