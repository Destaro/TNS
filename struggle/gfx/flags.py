import os
from PIL import Image #pip install pillow

input_folder = 'flags'
output_folder = 'compressed'
file_size_x = 93
file_size_y = 64
errors = 0

if not os.path.exists(output_folder):
    print("Output folder does not exist, creating one.")
    try:
        os.makedirs(output_folder)
    except Exception as e:
            print(f"Couldn't create output folder, maybe a pemissioning issue?.\n\n{e}")
            quit()
 

print("Starting compression....")
for filename in os.listdir(input_folder):
    if filename.lower().endswith('.tga'):
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename)
        try:
            with Image.open(input_path) as img:

                img = img.resize((file_size_x, file_size_y), Image.LANCZOS)
                img = img.convert('RGB')
                img.save(output_path, compression='tga_rle')

        except Exception as e:
            print(f"Error while compressing '{filename}', you should double check this file.")
            errors += 1
print("Finished!")
if errors > 0:
    print(f"There was {errors} errors, you should certainly double check those.")