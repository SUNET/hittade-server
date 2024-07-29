from django import forms


search_choices = {"package": "Package", "host": "Host"}


class PackageForm(forms.Form):
    package_name = forms.CharField(label="Package Name", max_length=255)
    package_version = forms.CharField(
        label="Package Version", max_length=255, required=False
    )


class SearchForm(forms.Form):
    search = forms.CharField(label="Search", max_length=255)
    stype = forms.ChoiceField(
        label="",
        choices=search_choices.items(),
        required=False,
        widget=forms.Select(attrs={"class": "select", "id": "standard-select"}),
    )
