from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify
import os
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF
from io import BytesIO
import zipfile
from PIL import Image
import base64
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# Configuration
ALLOWED_EXTENSIONS = {'pdf'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB

app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_pdf_page_as_image(file_data, page_num, zoom=2.0):
    """Convert PDF page to image for display and selection"""
    pdf_document = None
    try:
        pdf_document = fitz.open(stream=file_data, filetype="pdf")
        
        if page_num < 0 or page_num >= len(pdf_document):
            raise ValueError(f"Page {page_num + 1} does not exist")
        
        page = pdf_document[page_num]
        
        # Get original page dimensions (in PDF units)
        page_rect = page.rect
        page_width = page_rect.width
        page_height = page_rect.height
        
        print(f"Page {page_num + 1} original dimensions: {page_width} x {page_height}")
        print(f"Rendering at zoom: {zoom}")
        
        # Create transformation matrix for zoom
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page as image
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        
        # Clean up pixmap
        pix = None
        
        print(f"Image rendered successfully")
        
        return img_data, page_width, page_height, zoom
        
    except Exception as e:
        raise Exception(f"Error rendering page: {str(e)}")
    finally:
        if pdf_document:
            pdf_document.close()

def extract_pdf_section(file_data, page_num, x, y, width, height, zoom=2.0, output_format='png'):
    """Extract a specific section from a PDF page"""
    pdf_document = None
    new_doc = None
    try:
        pdf_document = fitz.open(stream=file_data, filetype="pdf")
        
        if page_num < 0 or page_num >= len(pdf_document):
            raise ValueError(f"Page {page_num + 1} does not exist")
        
        page = pdf_document[page_num]
        
        # Get the original page dimensions
        page_rect = page.rect
        original_width = page_rect.width
        original_height = page_rect.height
        
        print(f"Original page dimensions: {original_width} x {original_height}")
        print(f"Selection coordinates received: x={x}, y={y}, w={width}, h={height}")
        
        # Ensure coordinates are within page bounds
        pdf_x = max(0, min(x, original_width))
        pdf_y = max(0, min(y, original_height))
        pdf_width = min(width, original_width - pdf_x)
        pdf_height = min(height, original_height - pdf_y)
        
        print(f"Clipped coordinates: x={pdf_x}, y={pdf_y}, w={pdf_width}, h={pdf_height}")
        
        # Create rectangle for the selected area
        rect = fitz.Rect(pdf_x, pdf_y, pdf_x + pdf_width, pdf_y + pdf_height)
        
        print(f"Extraction rectangle: {rect}")
        
        if output_format.lower() == 'pdf':
            # Create new PDF with just this section
            new_doc = fitz.open()
            new_page = new_doc.new_page(width=pdf_width, height=pdf_height)
            
            # Insert the cropped area
            dest_rect = fitz.Rect(0, 0, pdf_width, pdf_height)
            new_page.show_pdf_page(dest_rect, pdf_document, page_num, clip=rect)
            
            output_buffer = BytesIO()
            new_doc.save(output_buffer)
            output_buffer.seek(0)
            
            result = output_buffer.getvalue(), 'pdf'
            return result
        else:
            # Extract as image with high resolution
            extraction_zoom = 3.0
            mat = fitz.Matrix(extraction_zoom, extraction_zoom)
            
            # Scale the rectangle for the extraction zoom
            scaled_rect = fitz.Rect(
                rect.x0 * extraction_zoom,
                rect.y0 * extraction_zoom,
                rect.x1 * extraction_zoom,
                rect.y1 * extraction_zoom
            )
            
            # Render the full page at high resolution
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            # Convert to PIL Image for cropping
            img = Image.open(BytesIO(img_data))
            
            # Clean up pixmap
            pix = None
            
            # Crop the image to the selected rectangle
            crop_box = (
                max(0, int(scaled_rect.x0)),
                max(0, int(scaled_rect.y0)),
                min(img.size[0], int(scaled_rect.x1)),
                min(img.size[1], int(scaled_rect.y1))
            )
            
            print(f"Crop box: {crop_box}")
            print(f"Image size: {img.size}")
            
            cropped_img = img.crop(crop_box)
            
            # Convert back to bytes
            output_buffer = BytesIO()
            cropped_img.save(output_buffer, format='PNG', optimize=True)
            output_buffer.seek(0)
            
            result = output_buffer.getvalue(), 'png'
            return result
        
    except Exception as e:
        raise Exception(f"Error extracting section: {str(e)}")
    finally:
        if new_doc:
            new_doc.close()
        if pdf_document:
            pdf_document.close()

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No file selected')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            pdf_document = None
            try:
                # Read file data into memory
                file_data = file.read()
                
                # Get total pages
                pdf_document = fitz.open(stream=file_data, filetype="pdf")
                total_pages = len(pdf_document)
                
                return render_template('section_selector.html', 
                                     filename=filename, 
                                     total_pages=total_pages,
                                     file_data=base64.b64encode(file_data).decode())
                
            except Exception as e:
                flash(f'Error processing PDF: {str(e)}')
                return redirect(request.url)
            finally:
                if pdf_document:
                    pdf_document.close()
        else:
            flash('Invalid file type. Please upload a PDF file.')
            return redirect(request.url)
    
    return render_template('section_upload.html')

@app.route('/get_page_image', methods=['POST'])
def get_page_image():
    """Get page as image for selection interface"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data received'})
            
        file_data = base64.b64decode(data['file_data'])
        page_num = data['page_num']
        zoom = data.get('zoom', 1.5)
        
        print(f"Getting page {page_num + 1} with zoom {zoom}")
        
        img_data, page_width, page_height, actual_zoom = get_pdf_page_as_image(file_data, page_num, zoom)
        
        # Convert to base64 for display
        img_b64 = base64.b64encode(img_data).decode()
        
        print(f"Page image generated successfully, size: {len(img_b64)} characters")
        
        return jsonify({
            'success': True,
            'image': f"data:image/png;base64,{img_b64}",
            'page_width': page_width,
            'page_height': page_height,
            'zoom': actual_zoom
        })
        
    except Exception as e:
        print(f"Error in get_page_image: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/extract_sections', methods=['POST'])
def extract_sections():
    """Extract selected sections and create downloadable file"""
    try:
        print("Extract sections endpoint called")
        data = request.get_json()
        
        if not data:
            print("No JSON data received")
            return jsonify({'success': False, 'error': 'No data received'}), 400
        
        print(f"Received data keys: {list(data.keys())}")
        
        file_data = base64.b64decode(data['file_data'])
        selections = data['selections']
        filename = data['filename']
        output_format = data.get('output_format', 'png')
        
        print(f"Processing {len(selections)} selections for file: {filename}")
        print(f"Output format: {output_format}")
        
        if not selections:
            return jsonify({'success': False, 'error': 'No sections selected'}), 400
        
        extracted_files = []
        
        for i, selection in enumerate(selections):
            print(f"Processing selection {i+1}: {selection}")
            
            page_num = selection['page']
            x = selection['x']
            y = selection['y']
            width = selection['width']
            height = selection['height']
            zoom = selection.get('zoom', 2.0)
            
            print(f"Selection {i+1} coordinates - PDF: x={x}, y={y}, w={width}, h={height}")
            
            # Extract the section
            section_data, file_ext = extract_pdf_section(
                file_data, page_num, x, y, width, height, zoom, output_format
            )
            
            print(f"Extracted section {i+1}, size: {len(section_data)} bytes")
            
            # Generate filename
            section_filename = f"page_{page_num + 1}_section_{i + 1}.{file_ext}"
            
            extracted_files.append({
                'data': section_data,
                'filename': section_filename
            })
        
        print(f"Successfully extracted {len(extracted_files)} files")
        
        if len(extracted_files) == 1:
            # Single file - return directly
            print("Returning single file")
            return send_file(
                BytesIO(extracted_files[0]['data']),
                as_attachment=True,
                download_name=extracted_files[0]['filename'],
                mimetype=f'application/{output_format}' if output_format == 'pdf' else 'image/png'
            )
        else:
            # Multiple files - create ZIP
            print("Creating ZIP file")
            zip_buffer = BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file_info in extracted_files:
                    zip_file.writestr(file_info['filename'], file_info['data'])
                
                # Add info file
                info_content = f"Extracted sections from: {filename}\n"
                info_content += f"Total sections: {len(extracted_files)}\n\n"
                info_content += "Section Details:\n"
                info_content += "-" * 50 + "\n"
                
                for i, selection in enumerate(selections):
                    info_content += f"Section {i + 1}:\n"
                    info_content += f"  Page: {selection['page'] + 1}\n"
                    info_content += f"  PDF Position: ({selection['x']:.1f}, {selection['y']:.1f})\n"
                    info_content += f"  PDF Size: {selection['width']:.1f}x{selection['height']:.1f}\n"
                    if 'displayX' in selection:
                        info_content += f"  Display Position: ({selection['displayX']:.1f}, {selection['displayY']:.1f})\n"
                        info_content += f"  Display Size: {selection['displayWidth']:.1f}x{selection['displayHeight']:.1f}\n"
                    info_content += f"  Zoom: {selection.get('zoom', 'N/A')}\n"
                    info_content += f"  File: {extracted_files[i]['filename']}\n"
                    info_content += "-" * 30 + "\n"
                
                zip_file.writestr("extraction_info.txt", info_content)
            
            zip_buffer.seek(0)
            
            # Generate ZIP filename
            name_without_ext = os.path.splitext(filename)[0]
            zip_filename = f"{name_without_ext}_sections.zip"
            
            print(f"Returning ZIP file: {zip_filename}")
            
            return send_file(
                zip_buffer,
                as_attachment=True,
                download_name=zip_filename,
                mimetype='application/zip'
            )
    
    except Exception as e:
        print(f"Error in extract_sections: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting PDF Section Extractor on port 1000...")
    app.run(
        debug=True,
        port=1000,
        host='0.0.0.0',
        threaded=True
    )