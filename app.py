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
    try:
        pdf_document = fitz.open(stream=file_data, filetype="pdf")
        
        if page_num < 0 or page_num >= len(pdf_document):
            raise ValueError(f"Page {page_num + 1} does not exist")
        
        page = pdf_document[page_num]
        
        # Create transformation matrix for zoom
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page as image
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        
        # Get page dimensions
        page_rect = page.rect
        page_width = page_rect.width
        page_height = page_rect.height
        
        pdf_document.close()
        
        return img_data, page_width, page_height, zoom
        
    except Exception as e:
        raise Exception(f"Error rendering page: {str(e)}")

def extract_pdf_section(file_data, page_num, x, y, width, height, zoom=2.0, output_format='png'):
    """Extract a specific section from a PDF page"""
    try:
        pdf_document = fitz.open(stream=file_data, filetype="pdf")
        
        if page_num < 0 or page_num >= len(pdf_document):
            raise ValueError(f"Page {page_num + 1} does not exist")
        
        page = pdf_document[page_num]
        
        # Convert coordinates from display (zoomed) to PDF coordinates
        pdf_x = x / zoom
        pdf_y = y / zoom
        pdf_width = width / zoom
        pdf_height = height / zoom
        
        # Create rectangle for the selected area
        rect = fitz.Rect(pdf_x, pdf_y, pdf_x + pdf_width, pdf_y + pdf_height)
        
        # Create transformation matrix for high quality
        mat = fitz.Matrix(3.0, 3.0)  # High resolution for extraction
        
        # Render only the selected area
        pix = page.get_pixmap(matrix=mat, clip=rect)
        
        if output_format.lower() == 'pdf':
            # Create new PDF with just this section
            new_doc = fitz.open()
            new_page = new_doc.new_page(width=rect.width, height=rect.height)
            
            # Insert the cropped area
            new_page.show_pdf_page(new_page.rect, pdf_document, page_num, clip=rect)
            
            output_buffer = BytesIO()
            new_doc.save(output_buffer)
            new_doc.close()
            output_buffer.seek(0)
            
            pdf_document.close()
            return output_buffer.getvalue(), 'pdf'
        else:
            # Return as image
            img_data = pix.tobytes("png")
            pdf_document.close()
            return img_data, 'png'
        
    except Exception as e:
        raise Exception(f"Error extracting section: {str(e)}")

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
            
            try:
                # Read file data into memory
                file_data = file.read()
                
                # Get total pages
                pdf_document = fitz.open(stream=file_data, filetype="pdf")
                total_pages = len(pdf_document)
                pdf_document.close()
                
                return render_template('section_selector.html', 
                                     filename=filename, 
                                     total_pages=total_pages,
                                     file_data=base64.b64encode(file_data).decode())
                
            except Exception as e:
                flash(f'Error processing PDF: {str(e)}')
                return redirect(request.url)
        else:
            flash('Invalid file type. Please upload a PDF file.')
            return redirect(request.url)
    
    return render_template('section_upload.html')

@app.route('/get_page_image', methods=['POST'])
def get_page_image():
    """Get page as image for selection interface"""
    try:
        data = request.get_json()
        file_data = base64.b64decode(data['file_data'])
        page_num = data['page_num']
        zoom = data.get('zoom', 1.5)
        
        img_data, page_width, page_height, actual_zoom = get_pdf_page_as_image(file_data, page_num, zoom)
        
        # Convert to base64 for display
        img_b64 = base64.b64encode(img_data).decode()
        
        return jsonify({
            'success': True,
            'image': f"data:image/png;base64,{img_b64}",
            'page_width': page_width,
            'page_height': page_height,
            'zoom': actual_zoom
        })
        
    except Exception as e:
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
        
        print(f"Received data keys: {data.keys()}")
        
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
            zoom = selection['zoom']
            
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
                    info_content += f"  Position: ({selection['x']:.0f}, {selection['y']:.0f})\n"
                    info_content += f"  Size: {selection['width']:.0f}x{selection['height']:.0f}\n"
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
    app.run(
        debug=True,
        port=1000,
        host='0.0.0.0',
        threaded=True
    )