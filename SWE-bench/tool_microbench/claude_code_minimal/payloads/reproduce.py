from django.forms import Form, formset_factory

class SimpleForm(Form):
    pass

# Create a formset with a clean method that raises an error
class BaseFormSet(formset_factory(SimpleForm, extra=1)):
    def clean(self):
        raise ValueError("This is a non-form error")

# Create an instance of the formset
formset = BaseFormSet()

# Try to validate the formset (this will trigger the error)
formset.is_valid()

# Get the non-form errors and print their HTML representation
non_form_errors = formset.non_form_errors()
print("Non-form errors HTML:")
print(non_form_errors.as_ul())

# Check if 'nonform' CSS class is present
if 'nonform' in non_form_errors.as_ul():
    print("\nThe 'nonform' CSS class is present.")
else:
    print("\nThe 'nonform' CSS class is NOT present.")