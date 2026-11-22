//
//  vert_pass_through.vsh
//
//  Created by bend on 06/09/13.
//  Copyright EA 2013. All rights reserved.
//

//%0define PASS_1_WRITE_COC

//%1define PASS_2_VERTICAL_BLUR

//%2define PASS_3_HORIZONTAL_BLUR

//%3define PASS_4_COMPOSIT

//%4define PASS_4_COMPOSIT
//%4define DEBUG_COC

//%5define PASS_4_COMPOSIT
//%5define DEBUG_BLUR

////////////////////////////////////////

//%feature PASS_1_WRITE_COC
//%feature PASS_2_VERTICAL_BLUR
//%feature PASS_3_HORIZONTAL_BLUR
//%feature PASS_4_COMPOSIT
//%feature DEBUG_COC
//%feature DEBUG_BLUR

//%precompile PASS_1_WRITE_COC
//%precompile PASS_2_VERTICAL_BLUR
//%precompile PASS_3_HORIZONTAL_BLUR
//%precompile PASS_4_COMPOSIT

// Derivation of gaussian blur effect described here:
// http://rastergrid.com/blog/2010/09/efficient-gaussian-blur-with-linear-sampling/

attribute vec3 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

uniform highp mat4 u_ModelToProj;
uniform highp float u_ViewportWidth;
uniform highp float u_ViewportHeight;

varying highp vec2 v_TexCoord0;

#if defined(PASS_1_WRITE_COC) || defined(PASS_4_COMPOSIT)

	void main()
	{
		v_TexCoord0 = a_TexCoord0;
		gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
	}

#endif // PASS_1_WRITE_COC || PASS_4_COMPOSIT

#if defined(PASS_2_VERTICAL_BLUR) || defined(PASS_3_HORIZONTAL_BLUR)

	varying highp vec2 v_TexCoord1;
	varying highp vec2 v_TexCoord2;
	//varying highp vec2 v_TexCoord3;
	//varying highp vec2 v_TexCoord4;

	void main()
	{
	#if defined(PASS_2_VERTICAL_BLUR)
		highp vec2 offset1 = vec2( 0.0, 1.5 / u_ViewportHeight );
		//highp vec2 offset2 = vec2( 0.0, 3.5 / u_ViewportHeight );
	#else
		highp vec2 offset1 = vec2( 1.5 / u_ViewportWidth, 0.0 );
		//highp vec2 offset2 = vec2( 3.5 / u_ViewportWidth, 0.0 );
	#endif

		v_TexCoord0 = a_TexCoord0;
		v_TexCoord1 = a_TexCoord0 + offset1;
		v_TexCoord2 = a_TexCoord0 - offset1;
		//v_TexCoord3 = a_TexCoord0 + offset2;
		//v_TexCoord4 = a_TexCoord0 - offset2;

		gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
	}

#endif // PASS_2_VERTICAL_BLUR || PASS_3_HORIZONTAL_BLUR

